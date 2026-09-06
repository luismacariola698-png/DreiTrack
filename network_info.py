from __future__ import annotations
from app.network import network_access_context

def main() -> None:
    info = network_access_context()
    print()
    print('=' * 56)
    print('DreiTrack Private Network Information')
    print('=' * 56)
    print(f"Mode: {('LAN enabled' if info['enabled'] else 'Local computer only')}")
    print(f"Server computer: {info['hostname']}")
    print(f"Port: {info['port']}")
    print(f"Local address: {info['local_url']}")
    print()
    if info['enabled']:
        print('Company-network addresses:')
        for url in info['urls']:
            print(f'  {url}')
        print()
        print('Employees should use one of these addresses while connected')
        print('to the same private company network.')
    else:
        print('Private LAN access is disabled.')
        print('Run Enable Private Network Access.bat once on this server computer.')
    print()
    print('Do not forward this port on the public internet router.')
    print()
if __name__ == '__main__':
    main()
