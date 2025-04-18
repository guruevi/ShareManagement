import json
import logging

from jinja2 import Template
from paramiko.client import SSHClient, AutoAddPolicy
from paramiko.ssh_exception import SSHException
from requests import get, post, put, RequestException
from requests.auth import HTTPBasicAuth

from helpers.parsers import parse_output


def local_exec_command(server_config, command, arguments):
    raise NotImplementedError("Local command execution is not implemented.")


def map_output(web_output, command_type, mapping):
    """
    Maps the dict output from a web call to the expected dictionary structure using Jinja2 templates.

    Args:
        web_output (dict): The output from the web call.
        command_type (str): The type of command (not used in this implementation but kept for signature consistency).
        mapping (dict): The mapping structure with Jinja2 templates or hardcoded values.

    Returns:
        dict: The mapped output with resolved templates and hardcoded values.

    Example:
        web_output = {
            "quota": {
                "hard_limit": "100000",
                "soft_limit": "80 GiB"
            },
            "user": {
                "name": "John Doe",
                "email": "john.doe@example.com"
            }
        }

        mapping = {
            "quota": {
                "hard": "{{ quota.hard_limit | int }}",
                "soft": "{{ quota.soft_limit | replace(' GiB', '000') | int }}"
            },
            "user": {
                "name": "{{ user.name | capitalize }}",
                "email": "{{ user.email | lower }}"
            },
            "status": "active"  # Hardcoded value
        }
    """
    def recursive_map(structure, data):
        """Recursively maps the structure using Jinja2 templates."""
        if isinstance(structure, dict):
            return {key: recursive_map(value, data) for key, value in structure.items()}
        elif isinstance(structure, list):
            return [recursive_map(item, data) for item in structure]
        elif isinstance(structure, str):
            # Render the string as a Jinja2 template
            template = Template(structure)
            return template.render(**data)
        else:
            return structure

    return recursive_map(mapping, web_output)


def exec_command(server_config, command_type, arguments: dict):
    """
    Executes a command on the server and returns the output.
    """
    command_list = server_config[f"{command_type}_command"]
    output = []

    for raw_command in command_list:
        # Render the command with Jinja2
        template = Template(raw_command)
        command = template.render(**arguments)

        logging.debug(f"Command executing: {command}")
        if command.startswith("SSH#"):
            raw_output = ssh_exec_command(server_config, command[4:], arguments)
        elif command.startswith("WEB#"):
            raw_output = web_exec_command(server_config, command[4:], arguments)
        elif command.startswith("LOCAL#"):
            raw_output = local_exec_command(server_config, command[6:], arguments)
        else:
            raise NotImplementedError(f"Unsupported command prefix for {command_type}, should be SSH#, WEB# or LOCAL#")

        # If there is a regexp directive, parse it through that
        if f"{command_type}_regexp" in server_config:
            raw_output = parse_output(str(raw_output), command_type, server_config[f"{command_type}_regexp"])

        # There is no regexp directive, and we're still a string, then we should have returned JSON
        if isinstance(raw_output, str):
            try:
                raw_output = json.loads(raw_output)
            except json.JSONDecodeError:
                logging.debug(f"Failed to parse JSON output, not JSON?: {raw_output}")
                raw_output = {"output": raw_output}

        if f"{command_type}_mapper" in server_config:
            raw_output = map_output(raw_output, command_type, server_config[f"{command_type}_mapper"])

        output.append(raw_output)
        logging.debug(f"Output from command: {raw_output}")

    # Merge the dicts
    merged_output = {}
    for item in output:
        for key,value in item.items():
            if key in merged_output:
                merged_output[key].update(value)
            else:
                merged_output[key] = value
    logging.debug(merged_output)
    return merged_output

def ssh_exec_command(server_config, command, arguments: dict):
    """
    Executes a command on the server via SSH and returns the output.
    """
    logging.debug(f"Executing command: {command}")
    try:
        # Execute the command
        with SSHClient() as ssh:
            ssh.set_missing_host_key_policy(AutoAddPolicy())
            ssh.connect(server_config['ssh_host'],
                        username=server_config['ssh_username'],
                        password=server_config['ssh_password'])
            stdin, stdout, stderr = ssh.exec_command(command)
            exit_status = stdout.channel.recv_exit_status()
            if exit_status != 0:
                raise OSError(f"{command} failed with exit status {exit_status}: {stderr.read().decode('utf-8')}")
            output = stdout.read().decode('utf-8').strip()
    except SSHException as e:
        logging.error(f"SSH Error: {e}")
        raise
    logging.debug(f"Output: {output}")
    return output

def web_exec_command(server_config, command, arguments: dict):
    """
    Executes a command on the server via web interface and returns the output.
    """
    # We have GET# and POST# commands and PUT# commands
    auth = None
    headers = server_config.get("web_headers", {})
    if server_config.get("web_auth") == "basic":
        auth = HTTPBasicAuth(server_config["web_username"], server_config["web_password"])
    elif server_config.get("web_auth") == "bearer":
        headers["Authorization"] = f"Bearer {server_config['web_password']}"

    url = command.format(**arguments)
    data = {}
    # Parse data from command
    if ";data=" in command:
        data = json.loads(command.split(";data=")[1])
        url = command.split(";data=")[0]
        arguments["data"] = data

    logging.debug(f"Executing web command: {command}")
    try:
        # Parse the command and execute the appropriate HTTP request
        if url.startswith("GET#"):
            response = get(url[4:],  headers=headers, auth=auth, json=data)
        elif command.startswith("POST#"):
            response = post(url[5:], headers=headers, auth=auth, json=data)
        elif command.startswith("PUT#"):
            response = put(url[4:],  headers=headers, auth=auth, json=data)
        else:
            raise ValueError(f"Unsupported web command: {command}")

        response.raise_for_status()  # Raise an error for HTTP status codes 4xx/5xx
        output = response.text
    except RequestException as e:
        logging.error(f"Web command error: {e}")
        raise

    logging.debug(f"Web command output: {output}")
    return output