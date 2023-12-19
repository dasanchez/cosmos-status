'''
Build an address book of all validators in a given chain that includes:
- valoper address
- pubkey
- moniker
- consensus address
- validator address
- jailed or not
- last became inactive
- last became active

starting from a specified block height.
'''

from utils import utils
import argparse
import requests
import json
import csv
import os.path


class AddressBookBuilder():
    '''
    Assemble an address book using the API validators endpoint as a starting point.
    1. API: cosmosvaloper, pubkey, moniker
    2. RPC: bytes address
    3. keys parsing: cosmosvalcons, self-delegation addresses
    4. consumer chain keys
    '''
    # def __init__(self, rpc, api, start, end, output):
    def __init__(self, rpc, api, chain):
        self.rpc = rpc
        self.api = api
        self.chain_name = chain
        self.block = 1
        self.pubkey_address_dict = {}
        self.pubkey_valcons_dict = {}
        self.consumer_chains = []
        self.address_book = {}
        

    def load_pubkey_dicts(self, height):
        rpc_validators = utils.collect_rpc_validators(self.rpc, height)
        api_validator_set = utils.collect_api_validator_set(self.api, height)
        self.pubkey_address_dict = {
            val['pub_key']['value']: val['address']
            for val in rpc_validators
        }
        self.pubkey_valcons_dict = {
            val['pub_key']['value']: val['address']
            for val in api_validator_set
        }


    def populate_consumer_chain(self, chain: str):
        for _, val_data in self.address_book.items():
            cosmosvalcons = val_data['cosmosvalcons']
            consumer_valcons = ''
            val_data[chain] = {
                'cosmosvalcons': cosmosvalcons,
                'address': val_data['address']
            }
            if cosmosvalcons:
                consumer_valcons = utils.get_validator_consumer_address(
                    cosmosvalcons,
                    chain,
                    self.rpc
                )
            if consumer_valcons:
                val_data[chain]['cosmosvalcons'] = consumer_valcons
                val_data[chain]['address'] = utils.consensus_address_to_bytes(consumer_valcons)


    def save_csv(self):
        '''
        Saves the address book dict to a csv file
        '''
        val_list = []
        for pubkey, val in self.address_book.items():
            csv_entry = {
               'cosmosvaloper': val['cosmosvaloper'],
               'cosmos': val['cosmos'],
               'moniker': val['moniker'],
               'pubkey': pubkey,
               'address': val['address'],
               'cosmosvalcons': val['cosmosvalcons'],
               'bonded': val['bonded'],
            }
            for chain in self.consumer_chains:
                csv_entry[f'{chain}-cosmosvalcons'] = val[chain]['cosmosvalcons']
                csv_entry[f'{chain}-address'] = val[chain]['address']
            val_list.append(csv_entry)

        filename = f'{self.chain_name}-{self.block}-address-book.csv'
        with open(filename, 'w', encoding='utf-8') as output:
            fieldnames = [
                'cosmosvaloper',
                'cosmos',
                'moniker',
                'pubkey',
                'address',
                'cosmosvalcons',
                'bonded'
            ]
            for chain in self.consumer_chains:
                fieldnames.append(f'{chain}-cosmosvalcons')
                fieldnames.append(f'{chain}-address')
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(val_list)

    def build(self):
       
        self.block = int(utils.get_block(self.rpc)['header']['height'])
        self.load_pubkey_dicts(self.block)
        
        # 1. Get pubkey, cosmosvaloper, and moniker
        print('Getting API validator data')
        api_validators = utils.collect_api_validators(self.api, self.block)
        self.address_book = {
            val['consensus_pubkey']['key']: {
                'moniker': val['description']['moniker'],
                'cosmosvaloper': val['operator_address'],
                'cosmos': utils.cosmosvaloper_to_cosmos(val['operator_address']),
                'bonded': val['status'],
                'address': '',
                'cosmosvalcons': ''                
            } for val in api_validators
        }

        # 2. Populate address ans cosmosvalcons
        print("Populating addresses and valcons")
        for pubkey, address in self.pubkey_address_dict.items():
            self.address_book[pubkey]['address'] = self.pubkey_address_dict[pubkey]
        for pubkey, address in self.pubkey_address_dict.items():
            self.address_book[pubkey]['cosmosvalcons'] = self.pubkey_valcons_dict[pubkey]
        
        # 3. Populate consumer chain keys
        print("Populating consumer chain addresses")
        self.consumer_chains = utils.get_consumer_chains(self.api)
        for chain in self.consumer_chains:
            self.populate_consumer_chain(chain)

        filename = f'{self.chain_name}-{self.block}-address-book.json'
        with open(filename, 'w') as output:
            json.dump(self.address_book, output, indent=4)
        # 4. Save CSV
        self.save_csv()
        

parser = argparse.ArgumentParser(
    description='Build a validator address book.'
)
parser.add_argument('-r', '--rpc', type=str, help='RPC node address, including port')
parser.add_argument('-a', '--api', type=str, help='API node address, including port')
parser.add_argument('-c', '--chain', type=str, help='Chain name to use in filename', default='provider')
args = parser.parse_args()

RPC_NODE = args.rpc
API_NODE = args.api
CHAIN_NAME = args.chain

addressbook = AddressBookBuilder(RPC_NODE, API_NODE, CHAIN_NAME)
addressbook.build()
