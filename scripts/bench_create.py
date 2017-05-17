"""
Benchmark Bigchain throughput of CREATE transactions.

The throughput of BigchainDB cannot be measured just by posting transactions
via the web interface, because the process whereby they become part of the
valid set is asynchronous.

For this reason, this benchmark also monitors the size of the backlog, so that
transactions do not become stale, which can result in thrashing.

The benchmark runs for one minute and then dumps the statistics gathered by
graphite.

It should work in any environment as long as Docker Compose is available and the
containers that are created are separately namespaced under "benchcreate".

Happy benchmarking!
"""


import os
import sys
import time
import queue
import logging
import requests
import subprocess
import multiprocessing


def main():
    logging.basicConfig(level=logging.DEBUG)

    cmd(service + 'up -d mdb')
    cmd(service + 'up -d graphite')
    cmd(service + 'up -d bdb')

    out = cmd(service + 'port graphite 80', capture=True)
    graphite_web_port = out.strip().split(':')[1]
    logging.info('Graphite web interface at: http://localhost:%s/' % graphite_web_port)

    cmd(service + 'exec bdb python %s load' % sys.argv[0])


def load():
    from bigchaindb.core import Bigchain
    from bigchaindb.common.crypto import generate_key_pair
    from bigchaindb.common.transaction import Transaction

    def transactions():
        priv, pub = generate_key_pair()
        tx = Transaction.create([pub], [([pub], 1)])
        while True:
            i = yield tx.to_dict()
            tx.asset = {'data': {'n': i}}
            tx.sign([priv])

    def wait_for_up():
        logging.info('Waiting for server to start...')
        while True:
            try:
                requests.get('http://localhost:9984/')
                break
            except requests.ConnectionError:
                time.sleep(0.1)

    def post_txs():
        txs = transactions()
        txs.send(None)
        with requests.Session() as session:
            while True:
                i = tx_queue.get()
                if i is None:
                    break
                tx = txs.send(i)
                res = session.post('http://localhost:9984/api/v1/transactions/', json=tx)
                assert res.status_code == 202
                res.content

    num_threads = 20
    test_time = 100
    tx_queue = multiprocessing.Queue(maxsize=num_threads*2)
    txsi = iter(range(2<<32))
    start_time = time.time()
    b = Bigchain()
    timer = print_per_sec()
    
    wait_for_up()

    for i in range(num_threads):
        multiprocessing.Process(target=post_txs).start()

    while True:
        t = time.time()
        if t - start_time > test_time:
            break
        for i in range(500):
            tx_queue.put(txsi.__next__())
            timer.__next__()
        while b.connection.db.backlog.count() > 10000:
            time.sleep(0.1)

    for i in range(num_threads):
        tx_queue.put(None)

    while True:
        backlog = b.connection.db.backlog.count()
        if backlog > 0:
            print("%s txs in backlog" % backlog)
            time.sleep(1)
        else:
            break
    
    print('All done')

    # http://localhost:32822/render?target=stats_counts.vote.tx.valid&from=-150s


def print_per_sec():
    while True:
        t = time.time()
        for i in range(1<<32):
            yield
            if time.time() - t > 1:
                print('%s tx/s' % i)
                break
            
        


def cmd(command, capture=False):
    stdout = subprocess.PIPE if capture else None
    args = ['bash', '-c', command]
    proc = subprocess.Popen(args, stdout=stdout)
    assert not proc.wait()
    return capture and proc.stdout.read().decode()


service = 'docker-compose -p bench_create '


if sys.argv[1:] == ['load']:
    load()
else:
    main()


