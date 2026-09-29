
def convert_equip_to_list(data):
    ret = data.split(';')
    res = []
    for each in ret:
        temp = each.split(':')
        res.append((temp[0], temp[1],))
    return res
