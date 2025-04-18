import re

def parse_output(output, parser_type, regexp):
    """
    Parses the output of a command based on the server configuration and type.
    """
    if parser_type == "acl":
        return parse_acl(output, regexp)
    elif parser_type == "protocol":
        return parse_protocol(output, regexp)
    elif parser_type == "quota":
        return parse_quota(output, regexp)
    else:
        raise NotImplementedError("Parser type not implemented.")


def parse_protocol(output, regexp):
    protocols = {}
    for protocol in re.findall(regexp, output):
        protocols[protocol] = 1
    # Return protocols that are enabled
    return protocols

def parse_quota(output, regexp) -> dict[str, float]:
    # Get the quota from the output
    quota = {"soft": 0.0, "hard": 0.0}

    quota_match = re.search(regexp, output)
    if quota_match:
        for quota_type in ['soft', 'hard']:
            quota_raw = 0.0
            quota_unit = ''
            if f"{quota_type}_number" in quota_match.groupdict():
                quota_raw = quota_match.group(f"{quota_type}_number")
            if f"{quota_type}_unit" in quota_match.groupdict():
                quota_unit = quota_match.group(f"{quota_type}_unit")

            if quota_unit == 'P':
                quota_number = float(quota_raw) * 1024 * 1024
            elif quota_unit == 'T':
                quota_number = float(quota_raw) * 1024
            elif quota_unit == 'G':
                quota_number = float(quota_raw)
            elif quota_unit == 'M':
                quota_number = float(quota_raw) / 1024
            elif quota_unit == 'K':
                quota_number = float(quota_raw) / 1024 / 1024
            else:
                # Presume bytes
                quota_number = float(quota_raw) / 1024 / 1024 / 1024
            quota[quota_type] = quota_number
    return quota

def parse_acl(acl_output, acl_regexp):
    """Parses ACL output using regex patterns and permission map from the configuration."""
    parsed_data = {
        "owner": "nobody",
        "group": "nobody",
        "everyone": "everyone",
        "permissions": []
    }

    # Extract POSIX permissions and turn them into ACL
    for posix_type in ['owner', 'group', 'everyone']:
        entity_match = re.search(acl_regexp['regex_patterns'][posix_type], acl_output)
        if entity_match:
           parsed_data[posix_type] = entity_match.group(posix_type)

        posix_acl_match = re.search(acl_regexp['regex_patterns']['posix'], acl_output)
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
    permissions_pattern = acl_regexp['regex_patterns']['acl']
    permission_map = acl_regexp.get('permission_map', {})
    for match in re.finditer(permissions_pattern, acl_output):
        permission_matches = match.group('permission')
        translated_access = (permission_map.get(perm, perm) for perm in permission_matches.split(","))
        # We now have an array with ["", "r,w", "x", "r,w,x"] etc.
        # Remove empty string and flatten to a single set("r","w","x")
        unique_permissions = set()
        for perm in translated_access:
            if "r" in perm:
                unique_permissions.add("r")
            if "w" in perm:
                unique_permissions.add("w")
            if "x" in perm:
                unique_permissions.add("x")

        parsed_data['permissions'].append({
            "index": match.group('index'),
            "type": match.group('type'),
            "name": match.group('name'),
            "access": match.group('access'),
            "permission": unique_permissions
        })

    return parsed_data


