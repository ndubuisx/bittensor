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

import bittensor
import argparse
import copy
import sys
from munch import Munch

from . import executor_impl

from loguru import logger
logger = logger.opt(colors=True)

class executor:

    def __new__(
            cls,
            config: Munch = None, 
            wallet: 'bittensor.wallet' = None,
            subtensor: 'bittensor.Subtensor' = None,
            metagraph: 'bittensor.Metagraph' = None,
            axon: 'bittensor.Axon' = None,
            dendrite: 'bittensor.Dendrite' = None
        ) -> 'bittensor.Executor':
        r""" Creates a new Executor object from passed arguments.
            Args:
                config (:obj:`Munch`, `optional`): 
                    bittensor.executor.default_config()
                wallet (:obj:`bittensor.wallet`, `optional`):
                    bittensor wallet with hotkey and coldkeypub.
                subtensor (:obj:`bittensor.Subtensor`, `optional`):
                    Bittensor subtensor chain connection.
                metagraph (:obj:`bittensor.Metagraph`, `optional`):
                    Bittensor metagraph chain state.
                axon (:obj:`bittensor.Axon`, `optional`):
                    Bittensor axon server.
                dendrite (:obj:`bittensor.Dendrite`, `optional`):
                    Bittensor dendrite client.
        """
        if config == None:
            config = executor.default_config()
        config = copy.deepcopy(config)
        executor.check_config( config )
        if wallet == None:
            wallet = bittensor.wallet ( config = config )
        if subtensor == None:
            subtensor = bittensor.subtensor( config = config )
        if metagraph == None:
            metagraph = bittensor.metagraph( config = config)
        if axon == None:
            axon = bittensor.axon( config = config, wallet = wallet )
        if dendrite == None:
            dendrite = bittensor.dendrite( config = config, wallet = wallet )
        return executor_impl.Executor( config, wallet, subtensor, metagraph, axon, dendrite )
    
    @staticmethod
    def default_config () -> Munch:
        parser = argparse.ArgumentParser(); 
        executor.add_args(parser) 
        config = bittensor.config.Config.to_config(parser); 
        return config

    @staticmethod   
    def add_args (parser: argparse.ArgumentParser):
        bittensor.wallet.add_args( parser )
        bittensor.subtensor.add_args( parser )
        bittensor.axon.add_args( parser )
        bittensor.dendrite.add_args( parser )
        bittensor.metagraph.add_args( parser )
        bittensor.nucleus.Nucleus.add_args( parser )
        
    @staticmethod   
    def check_config (config: Munch):
        bittensor.wallet.check_config( config )
        bittensor.subtensor.check_config( config )
        bittensor.axon.check_config( config )
        bittensor.dendrite.check_config( config )
        bittensor.metagraph.add_args( config )
        bittensor.nucleus.Nucleus.check_config( config )