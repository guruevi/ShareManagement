from json import load
from ldap3 import Server, Connection, ALL

with open('configs/ad.json') as f:
    adConfig = load(f)

def lookup_user(query, search_by=None, exact=False) -> list[dict]:
    if not search_by:
        search_by = ["samAccountName", "mail", "givenName", "sn", "cn"]

    query, domain = split_domain(query)

    # Root is a special case, do not return it
    if query == "root":
        return []

    if query == "everyone":
        return [{"samAccountName": "Domain Users"}]

    """Search for a user in Active Directory by samAccountName, email, or name."""
    server = Server(adConfig[domain]["server"], get_info=ALL)
    conn = Connection(server, adConfig[domain]["user"], adConfig[domain]["password"], auto_bind=True)

    # Construct the search filter based on the search_by fields
    search_filter = f"(&(objectClass=user)(|"
    for field in search_by:
        search_filter += f"({field}={query}{'' if exact else '*'})"
    search_filter += "))"

    conn.search(adConfig[domain]["search_base"], search_filter, attributes=['samAccountName', 'mail', 'givenName', 'sn'])

    results = []
    for entry in conn.entries:
        results.append({
            'samAccountName': entry.samAccountName.value,
            'email': entry.mail.value,
            'first_name': entry.givenName.value,
            'last_name': entry.sn.value
        })
    conn.unbind()
    return results

def split_domain(query: str) -> (str, str):
    """Split the domain from the query string."""
    domain = ""
    if "@" in query:
        query_split = query.lower().split("@")
        domain = query_split[-1]
        query = query_split[0]
    elif "\\" in query:
        query_split = query.lower().split("\\")
        domain = query_split[0]
        query = query_split[-1]

    if not domain:
        # Default to the first domain in the config
        domain = list(adConfig.keys())[0]

    return query.lower(), domain.lower()

def lookup_group_members(query, account_attribute) -> set[str]:
    """Search for group members in Active Directory by group name and return their samAccountName."""
    query, domain = split_domain(query)

    # Root/Wheel is a special case, do not return it
    if query == "wheel" or query == "root":
        return set()

    if query == "everyone":
        return {"Domain Users"}

    server = Server(adConfig[domain]["server"], get_info=ALL)
    conn = Connection(server, adConfig[domain]["user"], adConfig[domain]["password"], auto_bind=True)

    # Search filter to match group name
    search_filter = f"(&(objectClass=group)(cn={query}))"
    conn.search(adConfig[domain]["search_base"], search_filter, attributes=['member'])

    results = set()
    for entry in conn.entries:
        for member_dn in entry.member:
            # Query each member's DN to get their desired attribute
            conn.search(member_dn, '(objectClass=*)', attributes=[account_attribute])
            if conn.entries:
                results.add(conn.entries[0][account_attribute].value)

    conn.unbind()
    return results