import logging
import time
import uuid
from copy import deepcopy, copy
from threading import Thread
from urllib.parse import unquote

from flask import Flask, render_template, request, redirect, url_for, jsonify
from flask_sqlalchemy import SQLAlchemy
import json

from helpers.commands import exec_command
from helpers.domain import lookup_user, lookup_group_members
from models.share import Share
from models.base import Base
from models.shareform import ShareForm

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'  # Replace with your database URI
db = SQLAlchemy(app)

# Form


# Load JSON Config
with open('configs/customers.json') as f:
    customerConfig_json = json.load(f)
    # Reorder the dictionary to make 'Generic' the first key
    customerConfig = {'Generic': customerConfig_json.pop('Generic')} if 'Generic' in customerConfig_json else {
        'parent': {'value': ''}, 'quota': {'value': 0}}
    customerConfig.update({k: customerConfig_json[k] for k in sorted(customerConfig_json)})

logging.basicConfig(level=logging.DEBUG)

with app.app_context():
    # Bind the Base to the SQLAlchemy instance
    Base.metadata.bind = db.engine
    Base.query = db.session.query_property()
    Base.metadata.create_all(bind=db.engine)  # Automatically create the database tables

    app.logger.setLevel(logging.DEBUG)

    # Create an item in the database for each customerConfig if it hasn't been created yet
    for customer, customer_share in customerConfig.items():
        existing_share = Share.query.filter_by(folder_name=customer_share['parent']['value']).first()
        if existing_share:
            continue

        existing_share = Share(customer=customer,
                               folder_name=customer_share.get('parent', {}).get('value', ''),
                               quota=int(customer_share.get('quota', {}).get('value', 0)),
                               server=customer_share.get('server', {}).get('value', ''),
                               protocol=customer_share.get('protocol', {}).get('value', 'nfs,smb'),
                               owner=customer_share.get('owner', {}).get('value', ''),
                               users=str(customer_share.get('owner', {}).get('value', '')),
                               permission=customer_share.get('permission', {}).get('value', 'rwx'),
                               # Never let desktop fix the permissions on underlying shares
                               can_fix=False
                               )
        db.session.add(existing_share)

    db.session.commit()

    # Update customerConfig with the IDs of existing shares - do not do this before creating the values
    for customer_share in customerConfig.values():
        existing_share = Share.query.filter_by(folder_name=customer_share['parent']['value']).first()
        customer_share['id'] = existing_share.id

with open('configs/servers.json') as f:
    serverConfig = json.load(f)

@app.route('/create', methods=['GET', 'POST'])
@app.route('/edit/<int:share_id>', methods=['GET', 'POST'])
def manage_share(share_id=None):
    form = ShareForm()
    edit_mode = share_id is not None
    share = Share.query.get(share_id) if edit_mode else Share()

    if edit_mode:
        form = ShareForm(obj=share)
        form.customer.choices = [(share.customer, share.customer)]
        form.server.choices = [(share.server, share.server)]
    else:
        # Populate customer choices from customerConfig keys
        form.customer.choices = [(key, key) for key in customerConfig.keys()]
        # Populate parent choices with existing shares and defined parents in config
        form.parent.choices = [(str(s.id), s.folder_name) for s in Share.query.all()]
        # Populate server choices from serverConfig keys
        form.server.choices = [(key, value['title']) for key, value in serverConfig.items()]

    if request.method == 'POST':
        # customer_data overrides field values
        customer_data = customerConfig[form.customer.data]
        for field, props in customer_data.items():
            # Skip if the field is defined, but not a dict (None or int)
            if not isinstance(props, dict) or not props.get('disabled'):
                continue
            # This field was disabled, do not override it
            if field == 'parent':
                # Find the parent ID in the database
                form[field].data = str(Share.query.filter_by(folder_name=props.get('value')).first().id)
            else:
                form[field].data = props.get('value', '')

        app.logger.debug(form.data)
        if not form.validate_on_submit():
            return render_template('create.html', form=form, edit_mode=edit_mode, config=customerConfig)

        if not edit_mode:
            # Prevent disaster by not allowing changes to various fields when editing
            share.customer = form.customer.data
            share.server = form.server.data
            # Get the folder name for the parent
            parent_folder_name = Share.query.get(form.parent.data).folder_name
            share.folder_name = f"{parent_folder_name}/{form.folder_name.data}"
            share.parent_id = int(form.parent.data) if form.parent.data else None  # Set parent

        # Protocols are stored as a comma-separated string
        share.protocol = form.protocol.data
        share.quota = int(form.quota.data)

        share.index = int(form.index.data)

        for field in ['owner', 'users', 'permission']:
            setattr(share, field, getattr(form, field).data)

        # Map ACL permissions to the template
        mapped_permission = serverConfig[share.server]['mapped_permission'][share.permission]
        share_dict = deepcopy(share.__dict__)
        share_dict.update({"mapped_permission": mapped_permission})

        if edit_mode:
            # Call Edit ACL
            exec_command(serverConfig[share.server], "edit_acl", share_dict)
        else:
            # Call Create ACL
            exec_command(serverConfig[share.server], "create_acl", share_dict)

        db.session.add(share)
        db.session.commit()
        return redirect(url_for('shares'))

    return render_template('create.html', form=form, edit_mode=edit_mode, config=customerConfig)


@app.route('/success/<int:share_id>')
def success(share_id):
    return f"Share created successfully with ID: {share_id}"


@app.route('/', methods=['GET', 'POST'])
def shares():
    search_query = request.args.get('search', '').strip()
    if search_query:
        all_shares = Share.query.filter(
            (Share.customer.ilike(f'%{search_query}%')) |
            (Share.folder_name.ilike(f'%{search_query}%')) |
            (Share.server.ilike(f'%{search_query}%')) |
            (Share.protocol.ilike(f'%{search_query}%')) |
            (Share.owner.ilike(f'%{search_query}%')) |
            (Share.users.ilike(f'%{search_query}%')) |
            (Share.permission.ilike(f'%{search_query}%'))
        ).all()
    else:
        all_shares = Share.query.all()
    render_servers = [(key, value['title']) for key, value in serverConfig.items()]
    return render_template('shares.html', shares=all_shares, search_query=search_query, servers=render_servers)


@app.route('/lookup_user', methods=['GET'])
def lookup_user_route():
    query = unquote(request.args.get('query', '')).strip()
    if not query or len(query) < 2:
        return jsonify([])  # Return empty list if no query provided or insufficient length
    # urldecode the query
    results = lookup_user(query)
    return jsonify(results)


@app.route('/delete', defaults={'share_id': None}, methods=['POST'])
@app.route('/delete/<int:share_id>', methods=['POST'])
def delete_share(share_id):
    share = Share.query.get_or_404(share_id)

    # We cannot delete POSIX permissions:
    if share.index < 0:
        return jsonify({"message": "Cannot delete POSIX permissions"}), 400

    # Delete from SQL but do not commit - we do this here in case the SSH fails
    # we commit after the SSH command succeeds
    db.session.delete(share)
    exec_command(serverConfig[share.server], "delete_acl", share.__dict__)
    db.session.commit()
    # Re-import the ACL from the server, because order may have changed
    import_acl_from_server(share.server, share.folder_name)
    return jsonify({"message": "Share deleted successfully"}), 200


# Simulated task queue and status storage
task_queue = {}
task_status = {}


def fix_permissions_task(task_id, share_id):
    try:
        # Simulate a long-running task
        time.sleep(10)  # Replace with actual logic
        task_status[task_id] = {'status': 'completed'}
    except Exception as e:
        task_status[task_id] = {'status': 'failed', 'message': str(e)}


@app.route('/api/fix_permissions', methods=['POST'])
def fix_permissions():
    data = request.get_json()
    # Coerce to integer
    share_id = int(data.get('share_id'))

    if not share_id:
        return jsonify({'message': 'Folder name is required'}), 400

    # Check if we are allowed to fix
    share = Share.query.get(share_id)

    if not share or not share.can_fix:
        return jsonify({'message': 'Permission denied'}), 403

    task_id = str(uuid.uuid4())
    task_status[task_id] = {'status': 'queued'}

    # Start the task in a separate thread
    thread = Thread(target=fix_permissions_task, args=(task_id, share_id))
    thread.start()

    return jsonify({'task_id': task_id}), 200


@app.route('/api/task_status/<task_id>', methods=['GET'])
def task_status_route(task_id):
    status = task_status.get(task_id)
    if not status:
        return jsonify({'message': 'Task not found'}), 404
    return jsonify(status)

@app.route('/import', methods=['POST'])
def import_share():
    data = request.get_json()
    server = data.get('server')
    folder = data.get('remote_folder')

    return import_acl_from_server(server, folder)


def import_acl_from_server(server, remote_folder):
    """
    Connects to a server via SSH, gets the ACL from the folder and adds the entry to the database.
    """
    parent_folder = "/".join(remote_folder.split('/')[:-1])
    parent = Share.query.filter_by(folder_name=parent_folder, server=server).first()
    if not parent:
        return jsonify({"message": "Parent folder not found"}), 404

    acl_output = exec_command(serverConfig[server], "acl", {"folder_name": remote_folder})
    quota_output = exec_command(serverConfig[server], "quota", {"folder_name": remote_folder})
    protocol_output = exec_command(serverConfig[server], "protocol", {"folder_name": remote_folder})

    owner_str = ""
    owner = lookup_user(acl_output['owner'], search_by=[serverConfig[server]["acl_ldap_attribute"]], exact=True)
    if owner:
        owner_str = owner[0][serverConfig[server]["acl_ldap_attribute"]]

    # Get the keys for each protocol that is not 0
    protocols = {key for key, value in protocol_output.items() if value != 0}
    quota = quota_output['hard']

    for acl in acl_output['permissions']:
        if acl['access'] == "deny":
            # Skip denied permissions
            continue
        elif acl['type'] == 'user':
            # Add the user to the users
            user = lookup_user(acl['name'], search_by=[serverConfig[server]["acl_ldap_attribute"]], exact=True)
            if not user:
                continue
            try:
                users = {user[0][serverConfig[server]["acl_ldap_attribute"]]}
            except KeyError:
                continue
        elif acl['type'] == 'group':
            # Add the group to the users
            users = lookup_group_members(acl['name'], serverConfig[server]["acl_ldap_attribute"])
        else:
            # This is an 'everyone' or unknown type, we presume the worst
            users = {acl_output['everyone']}

        users.discard('')
        users.discard(None)
        if not users:
            # Skip if group is empty
            continue

        # Find the existing ACL
        share = Share.query.filter_by(folder_name=remote_folder, index=acl['index']).first()
        if not share:
            share = Share()
        # Update the ACL
        share.customer = parent.customer
        share.folder_name = remote_folder
        share.quota = quota
        share.index = acl['index']
        share.server = server
        share.protocol = protocols
        share.owner = owner_str
        share.parent = parent
        share.permission = acl['permission']
        share.users = users
        # Add the user/group to the database
        db.session.add(share)

    # Commit changes to the database
    db.session.commit()

    return jsonify({"message": "Import completed successfully"}), 200


if __name__ == '__main__':
    app.run(debug=True)
