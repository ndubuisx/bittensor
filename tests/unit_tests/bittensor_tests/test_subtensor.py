import bittensor
import pytest

def test_create():
    subtensor = bittensor.subtensor()

def test_defaults_to_akatsuki( ):
    subtensor = bittensor.subtensor()
    assert subtensor.endpoint_for_network() in bittensor.__akatsuki_entrypoints__


def test_networks():
    subtensor = bittensor.subtensor( network = 'kusanagi' )
    assert subtensor.endpoint_for_network() in bittensor.__kusanagi_entrypoints__
    subtensor = bittensor.subtensor( network = 'akatsuki' )
    assert subtensor.endpoint_for_network() in bittensor.__akatsuki_entrypoints__

def test_network_overrides():
    config = bittensor.subtensor.config()
    subtensor = bittensor.subtensor(network='kusanagi',config=config)
    assert subtensor.endpoint_for_network() in bittensor.__kusanagi_entrypoints__
    subtensor = bittensor.subtensor(network='akatsuki', config=config)
    assert subtensor.endpoint_for_network() in bittensor.__akatsuki_entrypoints__

def test_connect_no_failure( ):
     subtensor = bittensor.subtensor(
         network = "kusanagi"
     )
     subtensor.connect(timeout = 1, failure=False)

subtensor = bittensor.subtensor(
     network = 'akatsuki'
)
subtensor.substrate.

def test_connect_success( ):
     subtensor.connect()

def test_neurons( ):
     neurons = subtensor.neurons()
     assert len(neurons) > 0
     assert type(neurons[0].ip) == int
     assert type(neurons[0].port) == int
     assert type(neurons[0].ip_type) == int
     assert type(neurons[0].uid) == int
     assert type(neurons[0].modality) == int
     assert type(neurons[0].hotkey) == str
     assert type(neurons[0].coldkey) == str

     neuron = subtensor.neuron_for_uid( 0 )
     assert neurons.ip == neuron['ip']
     assert neurons.port == neuron['port']
     assert neurons.ip_type == neuron['ip_type']
     assert neurons.uid == neuron['uid']
     assert neurons.modality == neuron['modality']
     assert neurons.hotkey == neuron['hotkey']
     assert neurons.coldkey == neuron['coldkey']

     neuron = subtensor.neuron_for_pubkey(neuron.hotkey)
     assert neurons.ip == neuron['ip']
     assert neurons.port == neuron['port']
     assert neurons.ip_type == neuron['ip_type']
     assert neurons.uid == neuron['uid']
     assert neurons.modality == neuron['modality']
     assert neurons.hotkey == neuron['hotkey']
     assert neurons.coldkey == neuron['coldkey']
     
def test_get_current_block():
     block = subtensor.get_current_block()
     assert (type(block) == int)

# def test_weight_uids( ):
#     weight_uids = subtensor.weight_uids_for_uid(0)
#     assert(type(weight_uids) == list)
#     assert(type(weight_uids[0]) == int)

# def test_weight_vals( ):
#     weight_vals = subtensor.weight_vals_for_uid(0)
#     assert(type(weight_vals) == list)
#     assert(type(weight_vals[0]) == int)

# def test_last_emit( ):
#     last_emit = subtensor.get_last_emit_data_for_uid(0)
#     assert(type(last_emit) == int)

# def test_get_active():
#     active = subtensor.get_active()
#     assert (type(active) == list)
#     assert (type(active[0][0]) == str)
#     assert (type(active[0][1]) == int)

# def test_get_stake():
#     stake = subtensor.get_stake()
#     assert (type(stake) == list)
#     assert (type(stake[0][0]) == int)
#     assert (type(stake[0][1]) == int)

# def test_get_last_emit():
#     last_emit = subtensor.get_stake()
#     assert (type(last_emit) == list)
#     assert (type(last_emit[0][0]) == int)
#     assert (type(last_emit[0][1]) == int)

# def test_get_weight_vals():
#     weight_vals = subtensor.get_weight_vals()
#     assert (type(weight_vals) == list)
#     assert (type(weight_vals[0][0]) == int)
#     assert (type(weight_vals[0][1]) == list)
#     assert (type(weight_vals[0][1][0]) == int)

# def test_get_weight_uids():
#     weight_uids = subtensor.get_weight_vals()
#     assert (type(weight_uids) == list)
#     assert (type(weight_uids[0][0]) == int)
#     assert (type(weight_uids[0][1]) == list)
#     assert (type(weight_uids[0][1][0]) == int)
