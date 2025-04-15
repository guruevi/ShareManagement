import re


def parse_acl_output(acl_output, acl_parser):
    """Parses ACL output using regex patterns and permission map from the configuration."""
    parsed_data = {
        "owner": "nobody",
        "group": "nobody",
        "everyone": "everyone",
        "permissions": []
    }

    # Extract POSIX permissions and turn them into ACL
    for posix_type in ['owner', 'group', 'everyone']:
        entity_match = re.search(acl_parser['regex_patterns'][posix_type], acl_output)
        if entity_match:
           parsed_data[posix_type] = entity_match.group(posix_type)

        posix_acl_match = re.search(acl_parser['regex_patterns']['posix'], acl_output)
        if not posix_acl_match:
            continue
        permission = set(posix_acl_match.group(posix_type))
        permission.discard('-')

        if not permission:
            continue

        parsed_data['permissions'].append({
            "index": -1,
            "type": posix_type,
            "name": parsed_data[posix_type],
            "access": "allow",
            "permission": permission
        })

    # Extract permissions
    permissions_pattern = acl_parser['regex_patterns']['acl']
    permission_map = acl_parser.get('permission_map', {})
    for match in re.finditer(permissions_pattern, acl_output):
        permission_matches = match.group('permission')
        translated_access = (permission_map.get(perm, perm) for perm in permission_matches.split(","))
        # We now have an array with ["", "r,w", "x", "r,w,x"] etc.
        # Remove empty string and flatten to a single set("r","w","x")
        unique_permissions = set(perm for perms in translated_access for perm in perms.split(",") if perm)

        parsed_data['permissions'].append({
            "index": match.group('index'),
            "type": match.group('type'),
            "name": match.group('name'),
            "access": match.group('access'),
            "permission": unique_permissions
        })

    return parsed_data


