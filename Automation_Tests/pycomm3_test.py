
from pycomm3 import LogixDriver

# PLC Connection Settings
PLC_IP = '10.64.28.97'  # Replace with your Echo Server IP

with LogixDriver(PLC_IP) as plc:

    # Print all struct types
    tag_list = plc.get_tag_list()
    for tag in tag_list:
        if tag['tag_type'] == 'struct':
            print(f'{tag['tag_name']}: {tag['data_type']['name']}')