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
    $ python miners/text/template_client.py

"""
import argparse
from logging import Logger, raiseExceptions
from loguru import logger; logger = logger.opt(colors=True)
import bittensor
import torch
import time
import wandb
import datetime
from qqdm import qqdm
from transformers import AutoModel,AutoTokenizer
from torch.nn.utils import clip_grad_norm_
from torch.nn.utils.rnn import pad_sequence
from threading import Thread, Lock

import os
import torch.nn.functional as F

class server(torch.nn.Module):
    def __init__(self, 
                config: 'bittensor.config' = None,
                pretrained: str = None,
                padding: bool =None, 
                interpolate: bool =None,
                inter_degree: str = None,
                model = None,
                tokenizer = None,
                mapping_function = None,
                token_remap = None,
                checking= None):
        r"""" Creates a server that serves up a pretrained miner on the bittensor network
        Args:
                config (:obj:`bittensor.Config`, `required`): 
                    bittensor.server.config()
                pretrained (:obj:string , `optional`):
                    name of the pretrained model from huggingface to use
                padding (:obj:bool, `optional`):
                    If the server should pad out to match the hidden units that the bittensor network is using
                    If set to False, it will instead create a mapping layer to do the same thing.
                interpolate (:obj:bool, `optional`):
                    If the server should interpolate between sequence length differences.
                    If set to false, there should be a mapping function that takes care of the differnces
                inter_degree (:obj:str, `optional`):
                    The Interpolate algorithm (nearest | linear | bilinear | bicubic | trilinear | area)
                model (:obj:torch.module, `optional`):
                    Overrides the huggingface pretrained model with your own pretrained model
                tokenizer (:obj:huggingface.tokenizer, `optional`):
                    Overrides the huggingface tokenizer with your tokenizer
                mapping_function (:obj:Callable, `optional`):
                    Custom mapping function that maps between sequence length differences between tokenizers
                token_remap (:obj:Callable, `optional`):
                    Custom function that maps between tokenizers (defaults to self.remapping_token)
        """
        super(server, self).__init__()
        if config == None: config = server.config()
        self.config = config;print(config)
        self.pretrained = pretrained if pretrained != None else config.server.pretrained
        self.pre_model = model if model != None else AutoModel.from_pretrained(self.pretrained)
        self.tokenizer = tokenizer if tokenizer != None else AutoTokenizer.from_pretrained(self.pretrained)

        self.final_dim =  bittensor.__network_dim__
        self.pre_dimension = self.pre_model.config.hidden_size
        self.device = config.server.device
        self.padding = padding if padding != None else config.server.padding
        self.interpolate = interpolate if interpolate != None else config.server.interpolate
        self.inter_degree = inter_degree if inter_degree != None else config.server.inter_degree
        self.checking = checking if checking != None else config.server.checking
        self.mapping_function= mapping_function
        self.token_remap = token_remap if token_remap != None else self.remapping_token
        self.axon = None


        if padding == False:
            self.mapping = torch.nn.Linear( self.pre_dimension, self.final_dim)

        self.decoder = torch.nn.Linear( self.final_dim, bittensor.__vocab_size__ , bias=False)
        self.loss_fct = torch.nn.CrossEntropyLoss()

        if self.checking:
            self.check()
        
        
    def forward(self, inputs,tokenizer=None):
        """
            Forward pass through the pretrained model. 

            Args:
                pubkey ( str, `required`):
                    The public key of the caller.
                inputs ( :obj:`torch.Tensor`, `required`):
                    torch inputs to be forward processed.
                tokenizer (:obj:'huggingface.tokenizer', optional):
                    The tokenizer which was used to tokenize the inputs
             Returns:
                loss (:obj:`torch.FloatTensor`):
                    MLM loss from the inputs
                decoded_targets (:obj:`torch.FloatTensor`):
                    Decoded predictions of the next token in the sentence.

        """
        sen_len = inputs.size()
        inputs_remapped = self.token_remap(inputs,tokenizer)
        pre_hidden = self.pre_model(inputs_remapped).last_hidden_state

        if self.interpolate:
            down= F.interpolate(pre_hidden.unsqueeze(1),size=[sen_len[1],pre_hidden.size()[2]],mode=self.inter_degree).squeeze(1)
        elif self.mapping_function:
            down = self.mapping_function(pre_hidden,sen_len)
        else:
            raise Exception('interpolation off but no mapping function found. Please attach a mapping function')

        if self.padding:
            padding_l = (self.final_dim-self.pre_dimension)//2
            padding_r = (self.final_dim-self.pre_dimension) - padding_l
            encoded_hidden = F.pad(down, (padding_l, padding_r),  "constant", 0)
        else:
            encoded_hidden = self.mapping(down)
        decoded_targets = self.decoder(encoded_hidden)
        
        shift_logits = decoded_targets[..., :-1, :].contiguous()
        shift_labels = inputs[..., 1:].contiguous()     
        loss = self.loss_fct( shift_logits.view(-1, shift_logits.size(-1)), shift_labels.view(-1) ) 

        return loss, decoded_targets
    
    def encode_forward(self,inputs,tokenizer=None):
        r""" Subscribed to an axon servicing endpoint: processes forward messages from the wire.
            The arguments reflect an RPC request from another miner in the network, the response tensor
            should be the hidden units computed using the local context and with shape: [batch_size, sequence_len, __network_dim__].

            Args:
                inputs ( :obj:`torch.Tensor`, `required`):
                    torch inputs to be forward processed.
                tokenizer ( huggingface.tokenizer, `required`):
                    modality of inputs e.g. bittensor.proto.Modality.TEXT.

            Returns:
                outputs (:obj:`torch.FloatTensor`):
                    The nucleus's outputs as a torch tensor of shape [batch_size, sequence_len, __network_dim__]
        """
        sen_len = inputs.size()
        inputs = self.token_remap(inputs,tokenizer)
        pre_hidden = self.pre_model(inputs).last_hidden_state

        if self.interpolate:
            down= F.interpolate(pre_hidden.unsqueeze(1),size=[sen_len[1],pre_hidden.size()[2]],mode=self.inter_degree).squeeze(1)
        elif self.mapping_function:
            down = self.mapping_function(pre_hidden)
        else:
            raise Exception('interpolation off but no mapping function found. Please attach a mapping function')

        if self.padding:
            padding_l = (self.final_dim-self.pre_dimension)//2
            padding_r = (self.final_dim-self.pre_dimension) - padding_l
            encoded_hidden = F.pad(down, (padding_l, padding_r),  "constant", 0)
        else:
            encoded_hidden = self.mapping(down)
        return encoded_hidden

    def remapping_token(self,input, old_tokenizer):
        r""" Default remapping of tokenizers; decodes the message and then remaps the message using a new tokenizer
            Args:
                inputs_x ( :obj:`torch.Tensor`, `required`):
                    torch inputs to be forward processed.
                old_tokenizer ( huggingface.tokenizer, `required`):
                    modality of inputs e.g. bittensor.proto.Modality.TEXT.

        
        """
        if old_tokenizer == None:
            old_tokenizer = bittensor.tokenizer()
        new_data = []
        for i in range(input.shape[0]):
            decoded = old_tokenizer.decode(input[i]) 
            hugging = self.tokenizer(decoded)
            new_data += [torch.LongTensor(hugging.input_ids)]
        new_data = pad_sequence(new_data,batch_first=True)
        return new_data
    
    def start(self,wallet,optimizer):
        if self.axon != None:
            self.axon.start().subscribe()
        else:
            self.optimizer = optimizer
            self.axon = bittensor.axon (
                            wallet = wallet,
                            forward_text = self.forward_text,
                            backward_text = self.backward_text,
                        )
            self.axon.start().subscribe()

    # Define our forward function.
    def forward_text (self, pubkey, inputs_x ):
        return self.encode_forward( inputs_x.to(self.device) )

    # Define our backward function.
    def backward_text (self, pubkey:str, inputs_x, grads_dy ):
        with torch.enable_grad():
            with torch.autograd.set_detect_anomaly(True):
                mutex.acquire()
                outputs_y = self.encode_forward( inputs_x.to(self.device) )
                torch.autograd.backward (
                    tensors = [ outputs_y.to(self.device) ],
                    grad_tensors = [ grads_dy.to(self.device) ]
                )
                mutex.release()
                #self.optimizer.step() # Applies accumulated gradients.
                #self.optimizer.zero_grad() 
    
    def check(self):
        assert self.tokenizer.name_or_path == self.pre_model.name_or_path, 'incorrect model ({}) and tokenizer ({})'.format(self.pre_model.name_or_path,self.tokenizer.name_or_path)
        if self.interpolate == False:
            assert self.mapping_function != None, 'Incorrect '

    @staticmethod
    def config ():
        parser = argparse.ArgumentParser()
        parser.add_argument('--server.learning_rate', type=float, help='Training initial learning rate.', default=0.1)
        parser.add_argument('--server.momentum', type=float, help='optimizer momentum.', default=0.8)
        parser.add_argument('--server.clip_gradients', type=float, help='Implement gradient clipping to avoid exploding loss on smaller architectures.', default=1.0)
        parser.add_argument('--server.device', type=str, help='miner default training device cpu/cuda', default=("cuda" if torch.cuda.is_available() else "cpu"))
        parser.add_argument('--server.pretrained', type=str, help='pretrained model from hugging face',default='gpt2')
        parser.add_argument('--server.padding', type=bool, help='To pad out final dimensions',default='True')
        parser.add_argument('--server.interpolate', type=bool, help='To interpolate between sentence length',default='True')
        parser.add_argument('--server.inter_degree', type=str, help='Interpolate algorithm (nearest | linear | bilinear | bicubic | trilinear | area)', default='nearest')
        parser.add_argument('--server.name', type=str, help='Trials for this miner go in miner.root / (wallet_cold - wallet_hot) / miner.name ', default='template_server')
        parser.add_argument('--server.checking', type=bool, help='To check if server settings are correct',default='True')


        bittensor.wallet.add_args( parser )
        bittensor.axon.add_args( parser )
        bittensor.subtensor.add_args( parser )
        bittensor.logging.add_args( parser )
        bittensor.wandb.add_args(parser)
        return bittensor.config( parser )

def main( config ):

    # Load/Create our bittensor wallet.
    wallet = bittensor.wallet( config = config ).create()

    # Load/Sync/Save our metagraph.
    metagraph = bittensor.metagraph ( 
        subtensor = bittensor.subtensor( config = config )
    ).load().sync().save()

    # Instantiate the model we are going to serve on the network.
    # Miner training device.
    gp_server = server(config=config)

    # Create our optimizer.
    optimizer = torch.optim.SGD(
        [ {"params": gp_server.parameters()} ],
        lr = config.server.learning_rate,
        momentum = config.server.momentum,
    )

    # Create our axon server and subscribe it to the network.
    gp_server.start(wallet,optimizer)
    mutex = Lock()

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

    # --- Run Forever.
    for epoch in range(10000):
        print("epoch:",epoch)
        epoch_loss = 0
        epoch_batches = dataload.dataloader(epoch_length=100)
        for iteration, inputs in enumerate(epoch_batches):

            loss, _ = gp_server( inputs )
            loss.backward()

            mutex.acquire()
            clip_grad_norm_(gp_server.parameters(), 1.0)
            optimizer.step()
            optimizer.zero_grad()
            mutex.release()

            epoch_loss += loss.item()
            if iteration % 10 == 0:
                print('iteration {} loss'.format(iteration),loss.item())

        print("Epoch Loss:",epoch_loss/100)
        uid = metagraph.hotkeys.index( wallet.hotkey.ss58_address )
        wandb_data = {
            'Epoch': epoch,
            'loss': epoch_loss/100,
            'stake': metagraph.S[ uid ].item(),
            'rank': metagraph.R[ uid ].item(),
            'incentive': metagraph.I[ uid ].item(),
        } 
        wandb.log( wandb_data )

if __name__ == "__main__":
    main( server.config() )