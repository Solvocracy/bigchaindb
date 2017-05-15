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
import threading
import subprocess


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
        for i in range(1<<32):
            tx.asset = {'data': {'n': i}}
            print(i)
            tx.sign([priv])
            yield tx.to_dict()

    def wait_for_up():
        logging.info('Waiting for server to start...')
        while True:
            try:
                requests.get('http://localhost:9984/')
                break
            except requests.ConnectionError:
                time.sleep(0.1)

    def post_txs():
        while True:
            tx = tx_queue.get()
            if tx == None:
                break
            req = requests.post('http://localhost:9984/api/v1/transactions/', json=tx)
            assert req.status_code == 202

    num_threads = 5
    test_time = 100
    tx_queue = queue.Queue(maxsize=num_threads*2)
    txs = transactions()
    start_time = time.time()
    b = Bigchain()
    
    wait_for_up()

    for i in range(num_threads):
        threading.Thread(target=post_txs).start()

    while True:
        t = time.time()
        if t - start_time > test_time:
            break
        print("loop")
        for i in range(500):
            tx_queue.put(txs.__next__())
        while b.connection.db.backlog.count() > 10000:
            time.sleep(0.1)

    while b.connection.db.backlog.count() > 0:
        time.sleep(0.5)

    print('sent %s transactions' % i)


    # http://localhost:32822/render?target=stats_counts.vote.tx.valid&from=-150s



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


