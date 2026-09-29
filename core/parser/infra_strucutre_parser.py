from schemas.cde_schemas import InfrastructureRoomDetails


def convert_infra_to_storable(details: InfrastructureRoomDetails):
    data = [('Office', details.office_rooms, details.office_quantity,),
            ('Class Rooms', details.class_rooms, details.class_quantity,),
            ('Computer Lab', details.computer_lab_rooms, details.computer_lab_quantity,),
            ('Science Lab', details.science_lab_rooms, details.science_lab_quantity,),
            ('Library', details.library_rooms, details.library_quantity,)
            ]
    data = ';'.join([f"{each[0]}:{each[1]}:{each[2]}" for each in data])
    return data


def convert_infra_to_list(data):
    ret = data.split(';')
    res = []
    for each in ret:
        temp = each.split(':')
        res.append((temp[0], temp[1], temp[2],))
    return res
