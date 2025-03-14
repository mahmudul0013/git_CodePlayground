from pycomm3 import LogixDriver


if __name__ == '__main__':

    # PLC Connection Settings
    PLC_IP = '10.64.28.97'  # Replace with your Echo Server IP

    with LogixDriver(PLC_IP) as plc:
        tag_list = plc.get_tag_list("*")

        for tag in tag_list:
            if 'SPEED' in tag['tag_name'].upper():
                print(tag['tag_name'])
        pass
