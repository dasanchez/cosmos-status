import requests
import urllib
import command
import json

def get_block(urlRPC, height: int=0):
    if height > 0:
        response = requests.get(urlRPC + '/block?height=' + str(height)).json()
    else:
        response = requests.get(urlRPC + '/block' ).json()
    return response['result']['block']

def bytes_to_consensus_address(address, binary: str='gaiad'):
    """
    Converts bytes address to cosmosvalcons format
    """
    p = command.run([binary, "keys", "parse", address])
    res = p.output.split()[10]
    return res.decode("utf-8")

def consensus_address_to_bytes(address, binary: str='gaiad'):
    """
    Converts cosmosvalcons address to hex bytes format
    """
    p = command.run([binary, "keys", "parse", address, "--output", "json"])
    res = p.output.decode("utf-8")
    res_json = json.loads(res)
    return res_json['bytes']

def cosmosvaloper_to_cosmos(address, binary: str='gaiad'):
    """
    Converts bytes address to cosmos format
    """
    bytes_address = consensus_address_to_bytes(address, binary)
    p = command.run([binary, "keys", "parse", bytes_address, "--output", "json"])
    res = p.output.decode("utf-8")
    res_json = json.loads(res)
    return res_json['formats'][0]

def signatures_bytes_addrs(urlRPC, block: int=2):
    """
    Returns a list of the last commit's signatures for a given block
    in bytes format.
    """
    res = requests.get(f"{urlRPC}/commit?height={block}").json()['result']
    signatures = res['signed_header']['commit']['signatures']
    addresses = [sig['validator_address'] for sig in signatures if sig['validator_address']]
    return addresses

def signatures_consensus_addrs(urlRPC, block: int=2):
    """
    Returns a list of the last commit's signatures for a given block
    in cosmosvalcons format.
    """
    bytes_addresses = signatures_bytes_addrs(urlRPC, block)
    cons_addresses =  [bytes_to_consensus_address(address)
                        for address in bytes_addresses]
    return cons_addresses

def collect_api_validatorset(urlAPI, height: str='latest'):
    """
    Collects validatorsets info:
    - cosmosvalcons format
    - consensus pubkey
    - voting power
    - proposer priority
    """
    res = requests.get(f'{urlAPI}/validatorsets/{height}').json()
    return res['result']['validators']


def collect_rpc_validators(urlRPC, height: int=0):
    """
    Collects validators info at the latest block height
    - Address in bytes format
    - pubkey
    - voting power
    - proposer priority
    """
    page = 1
    if height > 0:
        response = requests.get(f"{urlRPC}/validators?page={page}&height={height}").json()['result']
    else:
        response = requests.get(f"{urlRPC}/validators?page={page}").json()['result']
    val_count = int(response['count'])
    total = int(response['total'])
    rpc_vals = response['validators']
    
    while val_count < total:
        page += 1
        if height > 0:
            response = requests.get(f"{urlRPC}/validators?page={page}&height={height}").json()['result']
        else:
            response = requests.get(f"{urlRPC}/validators?page={page}").json()['result']
        val_count += int(response['count'])
        rpc_vals.extend(response['validators'])
    # print(f'Collected {len(rpc_vals)} validators via RPC.')
    return rpc_vals

def collect_api_validators(urlAPI, height: int=0):
    """
    Collects the validators info at the specified height
    - operator address in cosmosvaloper format
    - consensus pubkey
    - jailed status
    - tokens
    - delegator shares
    - moniker
    - and more
    """
    if height > 0:
        response = requests.get(f"{urlAPI}/cosmos/staking/v1beta1/validators?pagination.limit=1000",
                        headers={'x-cosmos-block-height':f'{height}'}).json()
    else:
        response = requests.get(f"{urlAPI}/cosmos/staking/v1beta1/validators").json()
    total = int(response['pagination']['total'])
    api_vals = response['validators']
    next_key = response['pagination']['next_key']
    while next_key:
        response = requests.get(f'{urlAPI}/cosmos/staking/v1beta1/validators?pagination.limit=1000&pagination.key='
                   f'{urllib.parse.quote(next_key)}',
                   headers={'x-cosmos-block-height':f'{height}'}).json()
        api_vals.extend(response['validators'])
        next_key = response['pagination']['next_key']
    # print(f'Collected {len(api_vals)} validators via API') 
    return api_vals

def collect_api_validator_set(urlAPI, height: int=0):
    """
    Collects the validator set at the specified height
    - consensus address in cosmosvalcons format
    - consensus pubkey
    - proposer_priority
    - voting power
    """
    if height > 0:
        response = requests.get(f"{urlAPI}/validatorsets/{height}").json()
    else:
        response = requests.get(f"{urlAPI}/validatorsets/latest").json()
    api_vals = response['result']['validators']
    total = int(response['result']['total'])
    page = 2
    while len(api_vals) < total:
        if height > 0:
            response = requests.get(f"{urlAPI}/validatorsets/{height}?page={page}").json()
        else:
            response = requests.get(f"{urlAPI}/validatorsets/latest?page={page}").json()
        api_vals.extend(response['result']['validators'])
        page += 1
    return api_vals

def get_validator_info(urlAPI, urlRPC, height: int=0):
    """
    Cross-references API and RPC data using the public keys.
    """
    api_pubkey_dict = {}
    validator_rpc_dict = {}

    api_data = collect_api_validators(urlAPI, height)
    rpc_data = collect_rpc_validators(urlRPC, height)
    
    api_pubkey_dict = {val['consensus_pubkey']['key']: {
                         'moniker': val['description']['moniker'],
                         'operator_address': val['operator_address'],
                         'jailed': val['jailed'],
                         'tokens': val['tokens']}
                         for val in api_data}
    validator_rpc_dict = {}

    rpc_pubkey_dict = {val['pub_key']['value']: {
        'voting_power': int(val['voting_power']),
        'proposer_priority': int(val['proposer_priority']),
        'pubkey': val['pub_key']['value']}
        for val in rpc_data}
    
    for key in rpc_pubkey_dict:
        if key in api_pubkey_dict.keys():
            for rpc_key, rpc_value in api_pubkey_dict[key].items():
                rpc_pubkey_dict[key][rpc_key] = rpc_value

    return rpc_pubkey_dict

def get_cosmosvaloper_signatures(rpc_validators,
                                api_validatorset,
                                api_validators,
                                height: int=1):
    # Collect addresses in bytes format
    # We can only collect the signatures using the commit endpoint
    addrs_signed = signatures_bytes_addrs(rpc_validators, height)

    # Make dict of bytes address : pubkey
    rpc_val_set = collect_rpc_validators(rpc_validators, height=height)
   
    # print(f'collected {len(rpc_val_set)} rpc validators')
    
    addr_pubkey_dict = {val['address']: val['pub_key']['value']
        for val in rpc_val_set}
    
    # Make dict of pubkey: {cosmosvaloper, moniker}
    api_vals = collect_api_validators(api_validators)
    
    # print(f'collected {len(api_vals)} api validators')
    pubkey_valoper_dict = {val['consensus_pubkey']['key']:
                            {
                            'pubkey': val['consensus_pubkey']['key'],
                            'operator_address': val['operator_address'],
                            'moniker': val['description']['moniker']} for val in api_vals}

    # Get list of all validators that signed the block
    signatories = []
    for addr in addrs_signed:
        if addr in addr_pubkey_dict:
            if addr_pubkey_dict[addr] in pubkey_valoper_dict:
                pubkey_valoper_dict[addr_pubkey_dict[addr]]['address'] = addr
                signatories.append(pubkey_valoper_dict[addr_pubkey_dict[addr]])
            else:
                print(f'{addr_pubkey_dict[addr]} was not found in pubkey_valoper_dict')
        else:
            print(f'{addr} was not found in addr_pubkey_dict') 
    return signatories

def get_cosmosvaloper_signatures(addrs_signed,
                                rpc_validators,
                                api_validatorset,
                                api_validators,
                                height: int=1):
    # Make dict of bytes address : pubkey
    rpc_val_set = collect_rpc_validators(rpc_validators, height=height)
   
    # print(f'collected {len(rpc_val_set)} rpc validators')
    
    addr_pubkey_dict = {val['address']: val['pub_key']['value']
        for val in rpc_val_set}
    
    # Make dict of pubkey: {cosmosvaloper, moniker}
    api_vals = collect_api_validators(api_validators)
    
    # print(f'collected {len(api_vals)} api validators')
    pubkey_valoper_dict = {val['consensus_pubkey']['key']:
                            {
                            'pubkey': val['consensus_pubkey']['key'],
                            'operator_address': val['operator_address'],
                            'moniker': val['description']['moniker']} for val in api_vals}

    # Get list of all validators that signed the block
    signatories = []
    for addr in addrs_signed:
        if addr in addr_pubkey_dict:
            if addr_pubkey_dict[addr] in pubkey_valoper_dict:
                pubkey_valoper_dict[addr_pubkey_dict[addr]]['address'] = addr
                signatories.append(pubkey_valoper_dict[addr_pubkey_dict[addr]])
            else:
                print(f'{addr_pubkey_dict[addr]} was not found in pubkey_valoper_dict')
        else:
            print(f'{addr} was not found in addr_pubkey_dict') 
    return signatories

def get_validator_provider_address(address: str, chain_id: str, urlRPC: str, binary: str='gaiad'):
    """
    Obtain the provider validator address given a consumer chain id and the cosmosvalcons there
    """
    p = command.run([binary, "q", "provider", "validator-provider-key", chain_id, address, "--node", urlRPC, "--output", "json"])
    response = p.output.decode('utf-8')
    response_json = json.loads(response)
    return response_json['provider_address']

def get_validator_consumer_address(address: str, chain_id: str, urlRPC: str, binary: str='gaiad'):
    """
    Obtain the consumer validator address given its provider cosmosvalcons and the consumer chain id
    """
    p = command.run([binary, "q", "provider", "validator-consumer-key",
        chain_id, address, "--node", urlRPC, "--output", "json"])
    response = p.output.decode("utf-8")
    response_json = json.loads(response)
    return response_json['consumer_address']

def get_consumer_chains(urlAPI: str):
    '''
    Returns a list of consumer chains
    '''
    response = requests.get(f'{urlAPI}/interchain_security/ccv/provider/consumer_chains').json()
    if 'chains' in response:
        return [chain['chain_id'] for chain in response['chains']]
    return []
