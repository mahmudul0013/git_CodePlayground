from pylogix import PLC


def print_tag_list(tag_list):
    for tag in tag_list.Value:
        print(tag.TagName)

def print_all_tags(comm_obj):
    tag_list = comm_obj.GetTagList(True)
    print_tag_list(tag_list)

def print_program_tag_list(comm_obj):
    programs = comm_obj.GetProgramsList()
    for program_name in programs.Value:

        tag_list = comm_obj.GetProgramTagList(program_name)
        print_tag_list(tag_list)


with PLC() as comm:
    comm.IPAddress = '10.64.28.97'
    ret = comm.Read('A701_2_Monitor')
    ret = comm.Read('A701')
    ret = comm.Read('Simulation')
    ret = comm.Write('Simulation', 0)
    comm.Read("S01_IO_CP_Large:3:C", datatype="AB:1734_DI8:C:0")
    comm.GetPLCTime(True)
    programs = comm.GetProgramsList()


    # comm.GetProgramTagList()
    print(ret.TagName, ret.Value, ret.Status)
    print_all_tags(comm)