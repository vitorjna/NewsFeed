import shutil
import sys
import os
import argparse

data_types_mapping = {
    'config': 'config',
    'db': 'data',
    'logs': 'logs',
    'stats': 'stats'
}

def copy_data(data_type, external_dir, reverse=False):
    """
    Copies a data folder from the application to a specified external directory,
    or restores it from that directory back to the application.

    Args:
        data_type (str): The type of data to copy ('db', 'logs', 'stats', 'config').
        external_dir (str): The base external directory for backups.
        reverse (bool): If True, restores data from external_dir to the application.
    """
    if data_type not in data_types_mapping:
        print(f"Error: Unknown data type '{data_type}'. Valid types: {', '.join(data_types_mapping.keys())}")
        sys.exit(1)

    src_folder_name = data_types_mapping[data_type]

    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(script_dir, ".."))

    app_path = os.path.join(project_root, src_folder_name)
    backup_path = os.path.join(external_dir, data_type)

    full_src_path = backup_path if reverse else app_path
    full_dst_path = app_path    if reverse else backup_path
    action_verb   = "Restoring" if reverse else "Backing up"

    if not os.path.exists(full_src_path):
        print(f"Error: Source path '{full_src_path}' does not exist.")
        sys.exit(1)

    try:
        os.makedirs(os.path.dirname(full_dst_path) if reverse else external_dir, exist_ok=True)

        if os.path.exists(full_dst_path):
            print(f"Destination '{full_dst_path}' already exists. Overwriting...")
            if os.path.isdir(full_dst_path):
                def remove_readonly(func, path, exc_info):
                    import stat
                    os.chmod(path, stat.S_IWRITE)
                    func(path)
                shutil.rmtree(full_dst_path, onerror=remove_readonly)
            else:
                os.remove(full_dst_path)

        # Use shutil.copy to avoid "Operation not permitted" when copying metadata to some filesystems
        shutil.copytree(full_src_path, full_dst_path, copy_function=shutil.copy)
        print(f"Successfully {action_verb.lower()} '{data_type}' to '{full_dst_path}'")
    except shutil.Error as e:
        # Ignore EPERM errors from copystat on directories, which are wrapped in shutil.Error
        errors = [err for err in e.args[0] if not (isinstance(err, tuple) and len(err) >= 3 and "Operation not permitted" in str(err[2]))]
        if errors:
            print(f"Error during {action_verb.lower()}: {e}")
            sys.exit(1)
        else:
            print(f"Successfully {action_verb.lower()} '{data_type}' to '{full_dst_path}' (ignored permission errors)")
    except Exception as e:
        print(f"Error during {action_verb.lower()}: {e}")
        sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Copy or restore application data.")
    parser.add_argument("data_type", choices=list(data_types_mapping.keys()), help="Type of data to handle")
    parser.add_argument("external_dir", help="The base external directory for backups")
    parser.add_argument("--restore", dest="reverse", action="store_true", help="Restore data from the external directory back to the application")

    args = parser.parse_args()

    copy_data(args.data_type, args.external_dir, args.reverse)
