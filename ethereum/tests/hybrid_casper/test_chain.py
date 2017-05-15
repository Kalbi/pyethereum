import pytest
from ethereum import utils
from ethereum.tools import tester2
from ethereum.tests.utils import new_db
from ethereum.db import EphemDB
from ethereum.hybrid_casper import casper_utils
from ethereum.hybrid_casper.casper_utils import mk_prepare, mk_commit
from ethereum.slogging import get_logger
logger = get_logger()

_db = new_db()

# from ethereum.slogging import configure_logging
# config_string = ':info,eth.vm.log:trace,eth.vm.op:trace,eth.vm.stack:trace,eth.vm.exit:trace,eth.pb.msg:trace,eth.pb.tx:debug'
# configure_logging(config_string=config_string)

EPOCH_LENGTH = 23
SLASH_DELAY = 864
ALLOC = {a: {'balance': 5*10**19} for a in tester2.accounts[:10]}
k0, k1, k2, k3, k4, k5, k6, k7, k8, k9 = tester2.keys[:10]
a0, a1, a2, a3, a4, a5, a6, a7, a8, a9 = tester2.accounts[:10]


@pytest.fixture(scope='function')
def db():
    return EphemDB()
alt_db = db


@pytest.fixture(scope="module")
def accounts():
    k = utils.sha3(b'cow')
    v = utils.privtoaddr(k)
    k2 = utils.sha3(b'horse')
    v2 = utils.privtoaddr(k2)
    return k, v, k2, v2

def init_chain_and_casper():
    genesis = casper_utils.make_casper_genesis(k0, ALLOC, EPOCH_LENGTH, SLASH_DELAY)
    casper_address = utils.mk_contract_address(a0, genesis.get_nonce(a0) - 1)
    t = tester2.Chain(genesis=genesis)
    casper = tester2.ABIContract(t, casper_utils.casper_abi, casper_address)
    casper.initiate()
    return t, casper

def init_multi_validator_chain_and_casper(validator_keys):
    t, casper = init_chain_and_casper()
    mine_epochs(t, 1)
    for k in validator_keys[1:]:
        valcode_addr = t.tx(k0, '', 0, casper_utils.mk_validation_code(utils.privtoaddr(k)))
        assert utils.big_endian_to_int(t.call(k0, casper_utils.purity_checker_address, 0, casper_utils.ct.encode('submit', [valcode_addr]))) == 1
        casper.deposit(valcode_addr, utils.privtoaddr(k), value=3 * 10**18)
        t.mine()
    casper.prepare(mk_prepare(0, 1, epoch_blockhash(t, 1), epoch_blockhash(t, 0), 0, epoch_blockhash(t, 0), k0))
    casper.commit(mk_commit(0, 1, epoch_blockhash(t, 1), 0, k0))
    epoch_1_anchash = utils.sha3(epoch_blockhash(t, 1) + epoch_blockhash(t, 0))
    assert casper.get_consensus_messages__committed(1)
    mine_epochs(t, 1)
    assert casper.get_dynasty() == 1
    casper.prepare(mk_prepare(0, 2, epoch_blockhash(t, 2), epoch_1_anchash, 1, epoch_1_anchash, k0))
    casper.commit(mk_commit(0, 2, epoch_blockhash(t, 2), 1, k0))
    casper.get_consensus_messages__committed(2)
    mine_epochs(t, 1)
    assert casper.get_dynasty() == 2
    return t, casper

# Helper function for gettting blockhashes by epoch, based on the current chain
def epoch_blockhash(t, epoch):
    if epoch == 0:
        return b'\x00' * 32
    return t.head_state.prev_headers[epoch*EPOCH_LENGTH * -1 - 1].hash

# Mines blocks required for number_of_epochs epoch changes, plus an offset of 2 blocks
def mine_epochs(t, number_of_epochs):
    distance_to_next_epoch = (EPOCH_LENGTH - t.head_state.block_number) % EPOCH_LENGTH
    number_of_blocks = distance_to_next_epoch + EPOCH_LENGTH*(number_of_epochs-1) + 2
    return t.mine(number_of_blocks=number_of_blocks)

def test_mining(db):
    t, casper = init_chain_and_casper()
    assert t.chain.state.block_number == 0
    assert t.chain.state.block_difficulty == 1
    for i in range(2):
        t.mine()
        assert t.chain.state.block_number == i + 1

def test_mining_block_rewards(db):
    t, casper = init_chain_and_casper()
    genesis = t.mine(coinbase=a1)
    blk2 = t.mine(coinbase=a1)
    blk3 = t.mine(coinbase=a1)
    blk4 = t.mine(coinbase=a1)
    t.mine(coinbase=a1)
    assert t.chain.state.get_balance(a1) == t.chain.env.config['BLOCK_REWARD'] + t.chain.mk_poststate_of_blockhash(blk4.hash).get_balance(a1)
    assert t.chain.state.get_balance(a1) == t.chain.env.config['BLOCK_REWARD'] * 2 + t.chain.mk_poststate_of_blockhash(blk3.hash).get_balance(a1)
    assert t.chain.state.get_balance(a1) == t.chain.env.config['BLOCK_REWARD'] * 3 + t.chain.mk_poststate_of_blockhash(blk2.hash).get_balance(a1)
    assert t.chain.state.get_balance(a1) == t.chain.env.config['BLOCK_REWARD'] * 4 + t.chain.mk_poststate_of_blockhash(genesis.hash).get_balance(a1)
    assert blk2.prevhash == genesis.hash

def test_simple_chain(db):
    t, casper = init_chain_and_casper()
    t.tx(k0, a1, 20, gasprice=0)
    blk2 = t.mine()
    blk3 = t.mine()
    assert blk2.hash in t.chain
    assert blk3.hash in t.chain
    assert t.chain.has_block(blk2.hash)
    assert t.chain.has_block(blk3.hash)
    assert t.chain.get_block(blk2.hash) == blk2
    assert t.chain.get_block(blk3.hash) == blk3
    assert t.chain.head == blk3
    assert t.chain.get_children(blk2) == [blk3]
    assert t.chain.get_chain() == [blk2, blk3]
    assert t.chain.get_block_by_number(1) == blk2
    assert t.chain.get_block_by_number(2) == blk3
    assert not t.chain.get_block_by_number(3)

def test_head_change_for_longer_pow_chain(db):
    """" [L & R are blocks]
    Local: L0, L1
    add
    Remote: R0, R1, R2
    """
    t, casper = init_chain_and_casper()
    t.mine()
    root_hash = t.chain.head_hash
    L = t.mine(2)
    assert t.chain.head_hash == L.hash
    t.change_head(root_hash)
    R = t.mine(2)
    # Test that we just need one more block before the head switches
    assert t.chain.head_hash == L.hash
    R = t.mine(1)
    assert t.chain.head_hash == R.hash

def test_head_change_for_more_commits(db):
    """" [L & R are checkpoints. Ex: L0_4 is local chain, root epoch, with 4 stake weight]
    Local: L0_5, L1_1
    add
    Remote: R0_5, R2_1, R3_1
    """
    keys = tester2.keys[:5]
    t, casper = init_multi_validator_chain_and_casper(keys)
    epoch_1_anchash = utils.sha3(epoch_blockhash(t, 1) + epoch_blockhash(t, 0))
    epoch_2_anchash = utils.sha3(epoch_blockhash(t, 2) + epoch_1_anchash)
    # L0_5: Prepare and commit all
    for i, k in enumerate(keys):
        casper.prepare(mk_prepare(i, 3, epoch_blockhash(t, 3), epoch_2_anchash, 2, epoch_2_anchash, k))
        t.mine()
    for i, k in enumerate(keys):
        casper.commit(mk_commit(i, 3, epoch_blockhash(t, 3), 2 if i == 0 else 0, k))
        t.mine()
    epoch_3_anchash = utils.sha3(epoch_blockhash(t, 3) + epoch_2_anchash)
    root_hash = t.mine().hash
    # L1_1: Prepare all, commit 1
    mine_epochs(t, 1)
    for i, k in enumerate(keys):
        casper.prepare(mk_prepare(i, 4, epoch_blockhash(t, 4), epoch_3_anchash, 3, epoch_3_anchash, k))
        t.mine()
    casper.commit(mk_commit(0, 4, epoch_blockhash(t, 4), 3, keys[0]))
    L = t.mine()
    assert t.chain.head_hash == L.hash
    t.change_head(root_hash)
    # R2_1: Prepare all except v0, commit 1 -- Head will not change even with longer PoW chain
    mine_epochs(t, 2)
    for i, k in enumerate(keys[1:], 1):
        casper.prepare(mk_prepare(i, 5, epoch_blockhash(t, 5), epoch_3_anchash, 3, epoch_3_anchash, k))
        t.mine()
    casper.commit(mk_commit(1, 5, epoch_blockhash(t, 5), 3, keys[1]))
    R = t.mine()
    assert t.chain.head_hash == L.hash
    # # R3_1: Prepare all except v0, commit 1 -- Head will change
    # mine_epochs(t, 2)
    # for i, k in enumerate(keys[1:], 1):
    #     casper.prepare(mk_prepare(i, 5, epoch_blockhash(t, 5), epoch_3_anchash, 3, epoch_3_anchash, k))
    #     t.mine()
    # casper.commit(mk_commit(1, 5, epoch_blockhash(t, 5), 3, keys[0]))
    # t.mine()


# TODO: def test_add_longer_side_chain(db, alt_db):