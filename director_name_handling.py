def remove_name_suffixes(name):
    name_split = name.split()
    if len(name_split) == 1:
        return name
    while name_split[0].title() != name_split[0]:
        if len(name_split) == 1:
            # OK, I've messed up somehow. Emergency option
            return name.split()[0]
        name_split = name_split[1:]
    return name_split[0]
