def convert_data_to_storable(data):
    ret = []
    for each in data.get('marks'):
        marks = ''
        flag = 0
        for each_block in each:
            if flag != 0:
                marks += ','
            flag += 1
            id_marks = each_block.marks
            id_marks = 'null' if id_marks is None else id_marks
            marks += f'{each_block.id}:{id_marks}'

        ret.append(marks)

    return ret


def cmm_data_parser(data):
    res = []
    for each in data:
        d = each.split(',')
        r = []
        for each_d in d:
            id,marks = each_d.split(':')
            if marks == 'null':
                marks = None
            r.append({'id': id, 'marks': marks})
        res.append(r)
    return res
