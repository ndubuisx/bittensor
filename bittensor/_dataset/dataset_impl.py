""" Implementation for the dataset and GenesisTextDataset class, which handles dataloading from ipfs
"""
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

import os
import random

from torch.utils.data.dataloader import DataLoader
from torch.utils.data import Subset
import torch

from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
import requests

from loguru import logger
import bittensor
from .thread_queue import ThreadQueue
import time

logger = logger.opt(colors=True)

class Dataset():
    """ Implementation for the dataset class, which handles dataloading from ipfs
    """
    def __init__(self):
        
        # Used to retrieve directory contentx
        self.cat = 'http://ipfs.opentensor.ai/api/v0/cat' 
        self.node_get = 'http://ipfs.opentensor.ai/api/v0/object/get'
        self.mountain_hash = 'QmSdDg6V9dgpdAFtActs75Qfc36qJtm9y8a7yrQ1rHm7ZX'
        # Used when current corpus has been exhausted
        self.refresh_corpus = False
        

    @staticmethod
    def requests_retry_session(
            retries=10,
            backoff_factor=0.5,
            status_forcelist=(104, 500, 502, 504),
            session=None,
        ):
        """ Creates a retriable session for request calls. This enables
        automatic retries and back-off retries should any request calls fail.

        Args:
            retries (int, optional): Maximum number of retries. Defaults to 3.
            backoff_factor (float, optional): Factor by which to back off if a retry fails. Defaults to 0.3.
            status_forcelist (tuple, optional): A set of integer HTTP status codes that we should force a retry on. Defaults to (500, 502, 504).
            session ([type], optional): Session for which to set up the retries. Defaults to None.

        Returns:
            requests.Session(): A Requests Session object set up for retries and backoff.
        """

        session = session or requests.Session()
        retry = Retry(
            total=retries,
            read=retries,
            connect=retries,
            backoff_factor=backoff_factor,
            status_forcelist=status_forcelist,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        return session

    def retrieve_directory(self, address: str, params = None, action: str = 'post'):
        r"""Connects to Pinata IPFS gateway and retrieves directory.

        Returns:
            dict: A dictionary of the files inside of the genesis_datasets and their hashes.
        """
        session = requests.Session()
        session.params.update(params)
        if action == 'get':
            response = Dataset.requests_retry_session(session=session).get(address)
        elif action == 'post':
            response = Dataset.requests_retry_session(session=session).post(address)
        return response

    def __len__(self):
        """ Returns length of the dataset that the dataset is processing
        """

    def __getitem__(self, idx):
        """ Returns the next batch from the dataset.
        """

class GenesisTextDataset( Dataset ):
    """ One kind of dataset that caters for the data from ipfs 
    """
    def __init__(
        self,
        block_size,
        batch_size,
        max_corpus_size,
        num_workers,
        dataset_name,
        data_dir,
        save_dataset,
        max_datasets,
        no_tokenizer
    ):
        super().__init__()
        self.block_size = block_size
        self.batch_size = batch_size
        self.max_corpus_size = max_corpus_size
        self.num_workers = num_workers
        self.tokenizer = bittensor.tokenizer( version = bittensor.__version__ )
        self.dataset_name = dataset_name
        self.data_dir = data_dir
        self.save_dataset = save_dataset
        self.datafile_size_bound = 262158
        self.max_datasets = max_datasets
        self.__infinite_dataset_iterator = None
        self.no_tokenizer = no_tokenizer

        # Retrieve a random slice of the genesis dataset
        self.data = []
        self.data_remained = []

        # Used to refresh corpus if we've exhausted the whole dataset
        self.refresh_corpus = True

        self.build_hash_table()

        if not os.path.isdir(os.path.expanduser(data_dir)):
            os.makedirs(os.path.expanduser(data_dir))
            
        self.data_queue = ThreadQueue(
            producer_target = self.dataloader,
            producer_arg = (1000,),
            buffer_size = 2
        )

    def close(self):
        self.data_queue.close()

    def get_random_directories(self):
        r""" Getting directories from a random dataset_hash
        Where a directory could be leading to a data file or a directory file 

            Returns:
                directories (:type:`list`, `required`)
                    A list of directory.
                        directory: Map{ Name: str, Hash: str, Size: int }: 
                            A random directory that lead to a datafile.
        """
        
        # --- Getting directories from a random dataset hash.
        # --- directories: List[ Map{Name: str, Hash: str, Size: int} ]
        i = 0
        directories = [] 
        dataset_hashes_order = list(range(len(self.dataset_hashes)))
        random.shuffle(dataset_hashes_order)
        
        while i < self.max_datasets:
            
            dataset_key = list(self.dataset_hashes.keys())[dataset_hashes_order[i]]
            dataset_hash = self.dataset_hashes[dataset_key]
            i += 1
            logger.success("Loading dataset:".ljust(20) + "<blue>{}</blue>".format(dataset_key))
            response = self.retrieve_directory(self.cat, (('arg', dataset_hash),))
            
            if response.status_code != 200:
                logger.warning("Failed to retrieve directory, ignoring directory:".ljust(20) + "<blue>{}</blue>".format(dataset_key))
            
            else:
                # --- Get the directory links if there is valid response, else check on another dataset_hash 
                directories += response.json()
                logger.success("Loaded dataset:".ljust(20) + "<blue>{}</blue>".format(dataset_key))
                
        if len(directories) == 0:
            directories = None
        
        return directories

    def get_directories(self, keys: list):
        r""" Getting directories with names that matches keys.
        Where a directory could be leading to a data file or a directory file.

        Args:
            keys (:type:`list`, `required`): 
                The list of ipfs dataset names specified by the user to be included in the dataset.

        Returns:
            directories (:type:`list`, `required`)
                A list of directory.
                    directory: Map{ Name: str, Hash: str, Size: int }: 
                        A random directory that lead to a datafile.
        """
        directories = []
        for key in keys:
            
            if key in self.dataset_hashes.keys():
                logger.success("Loading dataset:".ljust(20) + "<blue>{}</blue>".format(key))
                dataset_hash = self.dataset_hashes[key] 
                response = self.retrieve_directory(self.cat, (('arg', dataset_hash),))
                if response.status_code != 200:
                    logger.warning("Failed to retrieve directory, ignoring directory:".ljust(20) + "<blue>{}</blue>".format(key))
                
                else:
                    # --- Get the directory links if there is valid response, else check on another dataset_hash 
                    directories += response.json()
                    logger.success("Loaded dataset:".ljust(20) + "<blue>{}</blue>".format(key))
            else:
                logger.error('Incorrect dataset name:'.ljust(20) + " <red>{}</red>.".format(key)+' Must be one of the following {}'.format(bittensor.__datasets__))

        return directories


    def extract_datafile_dir(self, directory):
        r"""
        With recursion, from the given directory, get a directory that leads to a datafile.

        Args:
            directory: Map{ Name: str, Hash: str, Size: int }: 
                The original directory to look up a datafile for.

        Returns:
            directory: Map{ Name: str, Hash: str, Size: int }: 
                A random directory that lead to a datafile.
        """
        # --- If the size of directory is small, it is leads to data file, return the data file.
        if directory['Size'] <= self.datafile_size_bound:
            return directory

        # --- Else, the directory leads to more directories, return a random data file within the directories.
        else:
            response = self.retrieve_directory(self.node_get, (('arg', directory['Hash']),))
            
            # --- Return none if the request failed.
            if response.status_code != 200:
                logger.warning("Failed to retrieve directory, ignoring directory:".ljust(20) + "<blue>{}</blue>".format(directory))
                return None
            
            # --- Pick a random sub_directory, run recursion until we have found a data file
            else:
                sub_directories = response.json()
                if sub_directories and 'Links' in sub_directories.keys() and len(sub_directories['Links']) >= 1:
                    random_sub_directory = random.choice(sub_directories['Links'])

                    # --- Fill the name of the random_sub_directory if it is empty. 
                    if random_sub_directory['Name'] == '':
                        random_sub_directory['Name'] = directory['Name']
                    
                    return self.extract_datafile_dir(random_sub_directory)
                else:
                    logger.warning("Directory seems empty, ignoring directory:".ljust(20) + "<blue>{}</blue>". format(dir_hash))
        return None

    def get_text(self, file):
        r"""
        Load the text data from disk if it is already in the the data_dir,
        else download it from IPFS and save it

        Args:
            file: Map{ Name: str, Hash: str, Size: int }
                The directory to get text file from.
        Returns:
            text: str: 
                The text data.
        """
        text = None
        file_name = file['Name']
        file_hash = file['Hash']
        full_path = os.path.expanduser(os.path.join(self.data_dir, file_name))

        # --- Load text from path
        if os.path.exists(full_path):
            try:
                with open(full_path, mode='r') as f:
                    text = f.read()
                logger.success("Loaded:".ljust(20) + "<blue>{}</blue>".format(file_name))
            except Exception:
                logger.warning("Load failed:".ljust(20) + "<blue>{}</blue>".format(file_name))

        # --- If couldnt load from path, download text.
        if text == None:
            response = self.retrieve_directory(self.node_get, (('arg', file_hash),))

            if response.status_code != 200:
                logger.warning("Failed to retrieve file, ignoring file:".ljust(20) + "<blue>{}</blue>".format(file_name))
            else:
                text = response.text
                logger.success("Downloaded:".ljust(20) + "<blue>{}</blue>".format(file_name))
                
                # --- Save text if the save_dataset flag is on.
                if self.save_dataset:
                    try:
                        with open(full_path, mode = 'w+') as f:
                            f.write(text)
                            logger.success("Saved:".ljust(20) + "<blue>{}</blue>".format(file_name))
                    except Exception:
                        logger.warning("Save failed:".ljust(20) + "<blue>{}</blue>".format(file_name))

        return text

    def construct_text_corpus(self, min_data_len = 0):
        """ Main function for generating the text data.
        1. Get directories from a random dataset_hash (dataset_hash is the result from calling pin/ls).
        2. Pick a random directory and get the directory that would lead to a datafile.    
        3. Get text from the directory.
        4. Repeat 2,3 until we have reached the max_corpus_size

        Returns:
            text: str: 
                Contents of the text data.
        """
        try:
            logger.success("Retrieving a dataset files from the IPFS gateway...")

            # --- Get directories from a random dataset_hash
            if self.dataset_name == 'default':
                directories = self.get_random_directories()
            else:
                directories = self.get_directories(self.dataset_name)
            data_corpus = []

            # --- Generate a random order of the directories
            directory_order = list(range(len(directories)))
            random.shuffle(directory_order)

            # --- Pick random directories and get their text contents.
            if directories:
                total_dataset_size = 0
                total_dataset_len = 0
                i = 0

                # --- Dont stop until the corpus size and the minimum data_length was reached.
                while (total_dataset_size <= self.max_corpus_size) or (total_dataset_len < min_data_len):
                    # --- Get a directory that leads to a datafile.
                    random_datafile_dir = self.extract_datafile_dir(directories[directory_order[i]])
                    
                    if random_datafile_dir == None:
                        pass

                    # --- Get text from the datafile directory
                    try:
                        text = self.get_text(random_datafile_dir)
                    except: 
                        text = None

                    if text != None:
                        text_list = text.split() 
                        data_corpus.extend(text_list)
                        total_dataset_size += int(random_datafile_dir['Size'])
                        total_dataset_len += len(text_list)
                    i += 1

                return data_corpus

            logger.error("It appears the directory is empty... Restart your miner to try again.")
            return []
        except Exception as e:
            logger.error("Ran into exception when trying to retrieve dataset from IPFS: {}".format(e))

        return []

    def dataloader(self, epoch_length = 100):
        """ Creates a torch dataloader out of a subclass of this class.

        Args:
            epoch_length (int, optional): The epoch length of the miner. If this length is not set or if it is larger than the dataset,
            then a dataloader for the entire dataset is returned. Otherwise, a dataloader for a subset of the dataset of epoch_length
            is returned. Defaults to None.

        Returns:
            torch.utils.data.dataloader.DataLoader: Pytorch dataloader.
        """
        data_size = epoch_length * self.batch_size * self.block_size
        
        # Make sure the data remained is at least as big as data_size 
        while len(self.data_remained) < (data_size) :
            self.data_remained += self.construct_text_corpus(min_data_len = data_size)

        self.data = self.data_remained[:data_size]
        del self.data_remained[:data_size]

        # Datalaoder calls self._getitem_ functions until the self.data uses up, and group the result by batch size
        return DataLoader(self,
                    shuffle=True,
                    batch_size=self.batch_size,
                    num_workers=self.num_workers,
                    drop_last=True)
    
    def set_dataset_iterator(self):
        r""" Get a new dataset that is ready from the queue. The result would be updated to self.__infinite_dataset_iterator__ . 
        """
        success = False 
        while not success: 
            if not self.data_queue.queue.empty() :
                dataset = self.data_queue.queue.get()
                if dataset:
                    self.__infinite_dataset_iterator = iter([input for input in dataset])
                    success = True
            else:
                time.sleep(2)

        return

    def __next__(self):
        """Returns the next element from the dataset. 
        """
        if self.__infinite_dataset_iterator == None:
            self.set_dataset_iterator()

        try:
            return next(self.__infinite_dataset_iterator)
        
        except StopIteration:
            self.set_dataset_iterator()
            return next(self.__infinite_dataset_iterator)

    def __len__(self):
        """Returns number of samples (blocks) of dataset

        Returns:
            length: int
        """
        if (self.data == None) or (self.block_size == None) or (self.block_size == 0):
            return 0
        return round( len(self.data) / self.block_size )

    def __getitem__(self, idx):
        """ Returns a block of sentences from text dataset.

            Args:
                idx: index of data input

            Returns:
                torch.tensor(dix)
        """
        start_idx = (idx * self.block_size) % len(self.data)
        end_idx = start_idx + self.block_size
        if self.no_tokenizer == False:
            tokenized_text = torch.tensor(self.tokenizer(" ".join(self.data[start_idx:end_idx]), padding=True, truncation=True)['input_ids'], dtype=torch.long)
        elif self.no_tokenizer == True:
            tokenized_text = " ".join(self.data[start_idx:end_idx])

        return tokenized_text[:self.block_size]

    def build_hash_table(self):
        self.dataset_hashes = {}
        response = self.retrieve_directory(self.node_get, (('arg', self.mountain_hash),))
        for i in response.json()['Links']:
            self.dataset_hashes[i['Name'][:-4]]= i['Hash'] 
