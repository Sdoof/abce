# Copyright 2012 Davoud Taghawi-Nejad
#
# Module Author: Davoud Taghawi-Nejad
#
# ABCE is open-source software. If you are using ABCE for your research you are
# requested the quote the use of this software.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License and quotation of the
# author. You may obtain a copy of the License at
#       http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations under
# the License.
import threading
import sqlite3
from collections import defaultdict
from .online_variance import OnlineVariance
import dataset

class Database(threading.Thread):
    def __init__(self, directory, in_sok, trade_log):
        threading.Thread.__init__(self)
        self.directory = directory
        self.panels = {}
        self.in_sok = in_sok
        self.data = {}
        self.trade_log = trade_log

        self.ex_str = {}
        self.aggregation = defaultdict(lambda : defaultdict(OnlineVariance))
        self.round = 0

    def add_trade_log(self):
        table_name = 'trade'
        self.database.execute("CREATE TABLE " + table_name +
                              "(round INT, good VARCHAR(50), seller VARCHAR(50), buyer VARCHAR(50), price FLOAT, quantity FLOAT)")
        return 'INSERT INTO trade (round, good, seller, buyer, price, quantity) VALUES (%i, "%s", "%s", "%s", "%s", %f)'

    def run(self):
        self.dataset_db = dataset.connect('sqlite:///' + self.directory + '/dataset.db')
        self.dataset_db.query('PRAGMA synchronous=OFF')
        self.dataset_db.query('PRAGMA journal_mode=OFF')
        self.dataset_db.query('PRAGMA count_changes=OFF')
        self.dataset_db.query('PRAGMA temp_store=OFF')
        self.dataset_db.query('PRAGMA default_temp_store=OFF')
        table_panel = {}
        table_log = {}
        current_log = defaultdict(list)
        current_trade = []
        self.table_aggregates = {}
        self.db = sqlite3.connect(self.directory + '/database.db')
        self.database = self.db.cursor()
        self.database.execute('PRAGMA synchronous=OFF')
        self.database.execute('PRAGMA journal_mode=OFF')
        self.database.execute('PRAGMA count_changes=OFF')
        self.database.execute('PRAGMA temp_store=OFF')
        self.database.execute('PRAGMA default_temp_store=OFF')
        # self.database.execute('PRAGMA cache_size = -100000')

        if self.trade_log:
            trade_table = self.dataset_db.create_table('trade___trade', primary_id='index')

        while True:
            try:
                msg = self.in_sok.get()
            except KeyboardInterrupt:
                break
            except EOFError:
                break

            if msg[0] == 'snapshot_agg':
                _, round, group, data_to_write = msg
                if self.round == round:
                    for key, value in data_to_write.items():
                        self.aggregation[group][key].update(value)
                else:
                    self.make_aggregation_and_write()
                    self.round = round
                    for key, value in data_to_write.items():
                        self.aggregation[group][key].update(value)

            elif msg[0] == 'trade_log':
                for (good, seller, buyer, price), quantity in msg[1].items():
                    current_trade.append({'round': msg[2],
                                          'good': good,
                                          'seller': seller,
                                          'buyer': buyer,
                                          'price': price,
                                          'quantity': quantity})
                    if len(current_trade) == 1000:
                        trade_table.insert_many(current_trade)
                        current_trade = []


            elif msg[0] == 'log':
                _, group, id, round, data_to_write, log_in_subround_or_serial = msg
                table_name = 'panel___%s___%s' % (group, log_in_subround_or_serial)
                data_to_write['round'] = round
                data_to_write['id'] = id
                current_log[table_name].append(data_to_write)
                if len(current_log[table_name]) == 1000:
                    if table_name not in table_log:
                        table_log[table_name] = self.dataset_db.create_table(table_name, primary_id='index')
                    table_log[table_name].insert_many(current_log[table_name])
                    current_log[table_name] = []


            elif msg == "close":
                break

            else:
                raise Exception(
                    "abce_db error '%s' command unknown ~87" % msg)

        self.db.commit()
        self.db.close()
        for name, data in current_log.items():
            if not name in self.dataset_db:
                table_log[name] = self.dataset_db.create_table(name, primary_id='index')
            table_log[name].insert_many(data)
        self.make_aggregation_and_write()
        self.dataset_db.commit()

    def make_aggregation_and_write(self):
        for group, table in self.aggregation.items():
            result = {'round': self.round}
            for key, data in table.items():
                result[key + '_ttl'] = data.sum()
                result[key + '_mean'] = data.mean()
                result[key + '_std'] = data.std()
            try:
                self.table_aggregates[group].insert(result)
            except KeyError:
                self.table_aggregates[group] = self.dataset_db.create_table(
                    'aggregate___%s' % group, primary_id='index')
                self.table_aggregates[group].insert(result)
            self.aggregation[group].clear()


class TableMissing(sqlite3.OperationalError):
    def __init__(self, message):
        super(TableMissing, self).__init__(message)


def is_convertable_to_float(x):
    try:
        float(x)
    except TypeError:
        if not(x):
            raise TypeError
        return False
    return True


def _number_or_string(word):
    """ returns a int if possible otherwise a float from a string
    """
    try:
        return int(word)
    except ValueError:
        try:
            return float(word)
        except ValueError:
            return word
