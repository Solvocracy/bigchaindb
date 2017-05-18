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
import requests
import subprocess
import multiprocessing


def main():
    cmd(service + 'up -d mdb')
    cmd(service + 'up -d graphite')
    cmd(service + 'up -d bdb')

    out = cmd(service + 'port graphite 80', capture=True)
    graphite_web_port = out.strip().split(':')[1]
    print('Graphite web interface at: http://localhost:%s/' % graphite_web_port)

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
        while True:
            try:
                requests.get('http://localhost:9984/')
                break
            except requests.ConnectionError:
                time.sleep(0.1)

    def post_txs():
        txs = transactions()
        txs.send(None)
        try:
            with requests.Session() as session:
                while True:
                    i = tx_queue.get()
                    if i is None:
                        break
                    tx = txs.send(i)
                    res = session.post('http://localhost:9984/api/v1/transactions/', json=tx)
                    assert res.status_code == 202
        except KeyboardInterrupt:
            pass

    num_clients = 30
    test_time = 60
    tx_queue = multiprocessing.Queue(maxsize=num_clients)
    txn = 0
    start_time = time.time()
    b = Bigchain()
    
    wait_for_up()

    for i in range(num_clients):
        multiprocessing.Process(target=post_txs).start()

    while time.time() - start_time < test_time:
        for i in range(500):
            tx_queue.put(txn)
            txn += 1
        while True:
            count = b.connection.db.backlog.count()
            if count > 10000:
                time.sleep(0.1)
            else:
                break
        processed = txn - count
        print('%.1f tx/s' % (processed / (time.time() - start_time)))

    for i in range(num_clients):
        tx_queue.put(None)

    print('Finished')
    print('%.1f tx/s' % (processed / (time.time() - start_time)))

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


