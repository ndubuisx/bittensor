#!/bin/python3
# The MIT License (MIT)
# Copyright © 2021 Yuma Rao

# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
# documentation files (the “Software”), to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all copies or substantial portions of
# the Software.

# THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
# THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.
""" The Exodus base client.

Example:
    $ python miners/text/server/template_client.py

"""
import argparse
from bittensor._metagraph.metagraph_impl import Metagraph
from logging import Logger, raiseExceptions
from loguru import logger; logger = logger.opt(colors=True)
import bittensor
import torch
import time
import wandb
import datetime
from qqdm import qqdm
from transformers import AutoModel,AutoTokenizer,AutoConfig
from torch.nn.utils import clip_grad_norm_
from torch.nn.utils.rnn import pad_sequence
from threading import Thread, Lock
from nuclei.server import server

import os
import torch.nn.functional as F


def main( config ):

    # Create Subtensor connection
    subtensor = bittensor.subtensor(config = config)

    # Load/Create our bittensor wallet.
    wallet = bittensor.wallet( config = config ).create()

    # Load/Sync/Save our metagraph.
    metagraph = bittensor.metagraph ( 
        subtensor = subtensor
    ).load().sync().save()

    # Instantiate the model we are going to serve on the network.
    # Miner training device.
    mutex = Lock()
    gp_server = server(config=config)
    
    # Create our optimizer.
    optimizer = torch.optim.SGD(
        [ {"params": gp_server.parameters()} ],
        lr = config.server.learning_rate,
        momentum = config.server.momentum,
    )
    threadpool = bittensor.prioritythreadpool(config=config)

    # Define our forward function.
    def forward_text (pubkey, inputs_x ):
        r""" Forward function that is called when the axon recieves a forward request from other peers
            Args:
                pubkey ( str, `required`):
                    The public key of the caller.
                inputs_x ( :obj:`torch.Tensor`, `required`):
                    torch inputs to be forward processed.

            Returns:
                outputs (:obj:`torch.FloatTensor`):
                    The nucleus's outputs as a torch tensor of shape [batch_size, sequence_len, __network_dim__]
        """ 
        def call(inputs):
            return gp_server.encode_forward( inputs )
        uid = metagraph.hotkeys.index(pubkey)
        priority = metagraph.S[uid].item()
        future = threadpool.submit(call,inputs=inputs_x.to(gp_server.device),priority=priority)
        try:
            return future.result(timeout= gp_server.config.server.timeout)
        except:
            raise TimeoutError('TimeOutError')

    # Define our backward function.
    def backward_text (pubkey:str, inputs_x, grads_dy ):
        r"""Backwards function that is called when the axon recieves a backwards request from other peers.
            Updates the server parameters with gradients through the chain.

            Args:
                pubkey ( str, `required`):
                    The public key of the caller.
                inputs_x ( :obj:`torch.Tensor`, `required`):
                    torch inputs from previous forward call.
                grads_dy ( :obj:`torch.Tensor`, `required`):
                    torch grads of forward output.
                    
        """
        def call(input,grad):
            with torch.enable_grad():
                with torch.autograd.set_detect_anomaly(True):
                    mutex.acquire()
                    outputs_y = gp_server.encode_forward( input )
                    torch.autograd.backward (
                        tensors = [ outputs_y ],
                        grad_tensors = [ grad ]
                    )
                    mutex.release()
        uid = metagraph.hotkeys.index(pubkey)
        priority = metagraph.S[uid].item()
        future = threadpool.submit(call, input=inputs_x.to( gp_server.device ), grad=grads_dy.to( gp_server.device ), priority=priority)
        try:
            return future.result(timeout= self.config.server.timeout)
        except:
            raise TimeoutError('TimeOutError')

    def blacklist(pubkey:str) -> bool:
        r"""Axon security blacklisting, used to blacklist message from low stake members
        Currently, this is not turned on.
        """
        uid =metagraph.hotkeys.index(pubkey)
        if metagraph.S[uid].item() < config.server.blacklist:
            return True
        else:
            return False

    # Create our axon server and subscribe it to the network.
    axon = bittensor.axon (
                wallet = wallet,
                forward_text = forward_text,
                backward_text = backward_text,
                blacklist= blacklist,
            ) 
    axon.start().subscribe()

    # Training Data
    dataload = bittensor.dataloader()
    full_path = os.path.expanduser('{}/{}/{}/{}'.format( config.logging.logging_dir, config.wallet.name, config.wallet.hotkey, config.server.name ))
    bittensor.logging( config = config,logging_dir = full_path)

    if not os.path.exists(full_path):
        os.makedirs(full_path)

    # --- Init Wandb.
    bittensor.wandb(
        config = config,
        cold_pubkey = wallet.coldkeypub,
        hot_pubkey = wallet.hotkey.public_key,
        root_dir = full_path
    )
    chain_weights =torch.zeros(metagraph.n)
    try:
        # --- Run 
        for epoch in range(10000):
            epoch_loss = 0
            epoch_batches = dataload.dataloader(epoch_length=10)
            for iteration, inputs in enumerate(epoch_batches):

                mutex.acquire()
                loss, _ = gp_server( inputs )
                loss.backward()
                clip_grad_norm_(gp_server.parameters(), 1.0)
                optimizer.step()
                optimizer.zero_grad()
                mutex.release()

                epoch_loss += loss.item()

            uid = metagraph.hotkeys.index( wallet.hotkey.ss58_address )
            wandb_data = {
                'Epoch': epoch,
                'loss': epoch_loss/10,
                'stake': metagraph.S[ uid ].item(),
                'rank': metagraph.R[ uid ].item(),
                'incentive': metagraph.I[ uid ].item(),
            } 
            gp_server.metagraph.sync().save()
            wandb.log( wandb_data )
            logger.info(wandb_data)
            chain_weights[uid] = 1 

            try: 
                did_set = subtensor.timeout_set_weights(
                    timeout=10,
                    uids=metagraph.uids,
                    weights = chain_weights,
                    wait_for_inclusion = True,
                    wallet = wallet,
                )
            except Exception as e:
                logger.error('Failure setting weights on chain with error: {}', e)

    except KeyboardInterrupt:
        # --- User ended session ----
        gp_server.axon.stop()


if __name__ == "__main__":
    main( server.config() )