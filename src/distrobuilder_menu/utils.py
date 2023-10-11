""" A collection of reusable utilities for python apps / scripts
"""
import fileinput
import inspect
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time
# python-yaml / libyaml (prevents pypy working)
import yaml

class Timer:
    """ Convenience class for timing code execution """

    def __init__(self, enabled):
        """ Prints execution time """
        self._start_time = None
        self.enabled = enabled

    def start(self):
        """ Start the Timer """
        if self.enabled:
            self._start_time = time.perf_counter()

    def stop(self, newline=None, post_msg=None):
        """Stop the timer, and report the elapsed time"""

        if self.enabled:
            elapsed_time = str(time.perf_counter() - self._start_time)
            # identify calling method
            caller = inspect.currentframe().f_back.f_code.co_name
            msg = f"DEBUG: {caller} executed in:{elapsed_time}"

            if post_msg:
                msg = f"{msg} {post_msg}"

            if newline:
                print('')

            print(msg)


def die(exit_code, *args):
    """concatenates error messages & exits. """
    print(' '.join(args))
    sys.exit(exit_code)


def get_input(prompt, regexp='[a-zA-Z]+', accept_empty=None, default='N', convert=str):
    """ Validates user input against regex & returns
        a configurable data type.
        Optionally accepts empty input & returns 'N'
    """
    valid = False
    while not valid:
        answer = input(prompt).strip()
        valid = re.match(regexp, answer)

        if accept_empty and len(answer) == 0:
            valid = True
            answer = default

    return convert(answer)


def edit_file(file_path, console_editor, regex='[a-zA-Z]+', question=None):
    """ Simple function to edit files using the console_editor set in
        USER_CONFIG yaml. Run the app with option -s to change the editor.
    """
    orig_size = Path(file_path).stat().st_size

    # uses 'Y' as the default choice
    if question:
        choice = get_input(question, regex, accept_empty=True, default='Y')
    else:
        choice = 'Y'

    if choice.startswith('y') or choice.startswith('Y'):
        try:
            # run shell command
            subprocess.run([console_editor, file_path], check=True)

            if orig_size != Path(file_path).stat().st_size:
                print(f"\nEdited: {file_path}")
            else:
                print(f"\nUnchanged: {file_path}")

        except subprocess.CalledProcessError as err:
            die(1, f"Error: {err.args[1]}")


def read_config(file_path, enabled=False):
    """ JSON / YAML config file loader in a single function.
    """
    # speedtest
    timer = Timer(enabled)
    timer.start()

    try:
        with open(file_path, 'r', encoding="utf-8") as config_file:
            # yaml.load() python implementation is 15 times slower
            # CBaseLoader is around 20% faster than the other C classes
            # but does not support boolean data types:
            # https://stackoverflow.com/a/72496031/555451
            config_data = yaml.load(config_file, Loader=yaml.CSafeLoader)
    except yaml.YAMLError as yaml_err:
        try:
            with open(file_path, 'r', encoding="utf-8") as config_file:
                config_data = json.load(config_file)
        except json.decoder.JSONDecodeError as json_err:
            die(1, f"Error: reading: {file_path} => {yaml_err} {json_err}")
    except IOError:
        die(1, f"Error: file does not exist ?: {file_path}")

    # speedtest
    timer.stop(newline=True, post_msg=file_path)
    return config_data


def write_config(outfile, data, data_type='yaml', yaml_sort=False, enabled=False):
    """ Write objects to yaml or json
    used by merge functions & user_config class
    """
    # speedtest
    timer = Timer(enabled)
    timer.start()

    # sanity check
    if len(data) == 0:
        die(1, f"Error: No data to write to: {outfile}")

    # create dir path if it doesn't exist
    dir_path = Path(outfile).parent
    if not dir_path.exists():
        print(f"Creating dirs: {dir_path}")
        dir_path.mkdir(parents=True)

    # write file as JSON or YAML
    try:
        with open(outfile, 'w', encoding="utf-8") as file:
            if data_type == 'json':
                file.write(json.dumps(data))
            else:
                # YAML not alpha sorted to preserve dictionary insertion order
                file.write(yaml.dump(data, sort_keys=yaml_sort))
            print(f"Wrote configuration as {data_type} to: {outfile}")

    except IOError:
        print(f"Error: could not write {data_type} to: {outfile}")
    except json.decoder.JSONDecodeError as json_err:
        print(f"JSON error: {json_err}")
    except yaml.YAMLError as yaml_err:
        print(f"YAML error: {yaml_err}")

    # speedtest
    timer.stop(newline=True, post_msg=outfile)


def find_files(file_or_pattern, dir_path):
    """ Returns a dictionary with filename without the extension
        as the key (as template files are named after the os) &
        the filepath as the value.
    """
    file_data = {}
    filepath_list = list(Path(dir_path).glob(file_or_pattern))

    if len(filepath_list) > 1:
        filepath_list.sort()

    for file_path in filepath_list:
        # stem is filename without the extension
        os_name = Path(file_path).stem
        file_data[os_name] = str(file_path)

    return file_data


def find_subdirs(dir_path, append_file=None):
    """returns a dictionary with:
       immediate subdir_name (key)
       immediate subdir_path (value)

       optionally pass append_file to modify subdir_path
    """
    subdir_data = {}

    # fast dir searches: https://stackoverflow.com/a/40347279/555451
    # os module is faster but was replaced with pathlib
    subdir_list = [x for x in Path(dir_path).iterdir() if x.is_dir()]

    if len(subdir_list) > 1:
        subdir_list.sort()

    for subdir_path in subdir_list:
        subdir_name = Path(subdir_path).name

        # cloudinit needs file paths for menu_edit()
        if append_file:
            subdir_data[subdir_name] = f"{subdir_path}/{append_file}"
        else:
            # cloudinit needs dir paths for menu_copy / rename / delete()
            # str returned here so move_files() doesn't break checking for \n
            subdir_data[subdir_name] = str(subdir_path)

    return subdir_data


def find_latest_files(target_dir, count):
    """ Finds the latest files in a directory

    Args:
        target_dir (str): search dir path
        count (int): number of items to return

    Returns:
        list: filenames found
    """
    cmd = f"ls -t {target_dir} | head -n{count}"

    try:
        output = subprocess.run(cmd, shell=True, text=True, capture_output=True, check=False)
    except subprocess.CalledProcessError as err:
        die(1, f"Error: finding last modified file {err.output[1]}")

    return output.stdout.splitlines()


def check_filepath(file_path):
    """ Convenience function for checking vars contain a valid path
    """
    try:
        Path(file_path).resolve()
    except (OSError, RuntimeError):
        die(1, f"Error: invalid path: {file_path}")


def check_command(command):
    """ Simple function to check a binary command exists
    """
    try:
        subprocess.run(command, shell=True, capture_output=True, check=False)
    except subprocess.CalledProcessError as err:
        die(1, f"Error running: '{command}' in check_command(): {err.args[1]}")


def preprend_lines(file, line_str):
    """Simple function to write file headers
    """
    try:
        with open(file, 'r', encoding="utf-8") as original:
            data = original.read()
        with open(file, 'w', encoding="utf-8") as modified:
            modified.write("\n".join([line_str, data]))
    # cross platform & also catches permission errors
    except (OSError, IOError) as err:
        print(f"Error: {err.args[1]} : {file}")


def yaml_extract(check_yq, input_file, out_file, node_key_regex):
    """ Extracts YAML node data from templates with the golang version of yq
        used to create template overrides
        pass in the node_key_regex string e.g:
        ^(files|packages)
        ^files
    """
    # optionally check yq exists
    if check_yq:
        check_command('yq -V | grep mikefarah')

    # extract YAML data
    # triple quote f-strings when they contain quotes (not needed on python 3.12)
    extract_cmd = f"""yq 'with_entries(select(.key | test("{node_key_regex}")))' {input_file}"""

    try:
        # write in append mode
        with open(out_file, "a", encoding="utf-8") as file_handle:
            subprocess.run(extract_cmd, shell=True, check=False, stdout=file_handle)

    # cross platform & also catches permission errors
    except (OSError, IOError) as err:
        die(1, f"Error: {err.args[1]} : {out_file}")

    # golang-yaml also removes the YAML header so insert it
    preprend_lines(out_file, '---\n')


def yaml_merge(check_yq, out_file, *input_files):
    """ Merges multiple YAML files with the golang version of yq
        python-yaml was problematic with multline strings - custom literal representers
        output YAML list objects enclosed in [] - yq merges YAML correctly with the only
        downside of removing blank lines (see insert_blank_lines() for the fix )
        * check_yq = Boolean
        * pass in multiple filepaths for *args
        based on a comment: https://stackoverflow.com/a/68201941/555451
    """
    # sanity checks
    check_filepath(out_file)

    # optionally check yq exists
    if check_yq:
        check_command('yq -V | grep mikefarah')

    # merge YAML files
    # f-strings don't work here as we need python to expand *input_files
    merge_cmd = " ".join(["yq eval-all '. as $item ireduce ({}; . *+ $item )'",
                          *input_files])
    try:
        with open(out_file, "w", encoding="utf-8") as file_handle:
            subprocess.run(merge_cmd, shell=True, check=False, stdout=file_handle)

    # cross platform & also catches permission errors
    except (OSError, IOError) as err:
        die(1, f"Error: {err.args[1]} : {out_file}")

    return out_file


def yaml_find_index(file, node, search_key, search_value):
    """Returns the index of a node in a YAML array
       that contains the search_key with the search_value

       Used for finding the node index that contains the
       cloud-init user-data so it can be populated with
       the contents of a YAML file.
    """
    data = read_config(file)
    array_list = data[node]
    counter = 0

    for item in array_list:
        if search_key in item and item[search_key] == search_value:
            break
        counter += 1

    return counter


def yaml_add_content(*, src_file, node, search_key, search_value, merge_file, new_key):
    """ Adds the contents of a file as a multiline string to a YAML node

        * Used by merge_cloudinit() to merge data to a template's 'content' key

        * Keyword-Only arguments (PEP 3102) avoids pylint: too-many-arguments
    """
    # pylint: disable=too-many-arguments
    arr_index = yaml_find_index(src_file, node, search_key, search_value)

    # extract YAML data
    # triple quote f-strings when they contain quotes (not needed in python 3.12)
    add_cmd = f"""yq -i '.{node}[{arr_index}].{new_key} = "'"$(< {merge_file})"'"' {src_file}"""

    try:
        subprocess.run(add_cmd, shell=True, check=False)
    # cross platform & also catches permission errors
    except (OSError, IOError) as err:
        die(1, f"Error: {err.args[1]}")


def insert_blank_lines(file, position, search_list):
    """ yq relies on golang-yaml which currently deletes blank lines in YAML
        this function edits files in place adding blank lines in the position
        of 'before' or 'after' lines matching a list of search strings.
    """
    previous_line = None

    for search in search_list:
        for line in fileinput.input(file, inplace=True):

            # don't insert a line if a previous blank line exists
            if previous_line and len(previous_line.strip()) != 0:

                if line.startswith(search):
                    if position == 'before':
                        line = line.replace(search, f"\n{search}")
                    else: # after
                        line = line.replace(search, f"{search}\n")

            previous_line = line
            sys.stdout.write(line)

    fileinput.close()


def move_file(file_path, new_path):
    """ Convenience function for renaming files

    Args:
        file_path (str): source file path
        new_path (str): new file path
    """
    # shell commands captured via subprocess can sometimes add '\n'
    if '\n' in file_path:
        die(1, f"Error: newline detected in: {file_path}")
    if '\n' in new_path:
        die(1, f"Error: newline detected in: {new_path}")

    # move / rename file or dir
    if Path(file_path).exists():
        try:
            shutil.move(file_path, new_path)
            print(f"\nRenamed:\n\n {file_path}")
            print(f" =======> {new_path}\n")
        except PermissionError:
            print(f"Error: permission denied moving: {file_path}")
        except NotADirectoryError:
            print(f"Error: check destination path exists: {new_path}")
    else:
        print(f"Error: source file does not exist: {file_path}")


def copy_dirs_or_files(src, dest):
    """ Copy files or folders

    Args:
        src (Path): source file or dir
        dest (Path): destination dir
    """
    if Path(src) and Path(dest):
        try:
            if Path(src).is_dir():
                # copy dirs
                shutil.copytree(src, dest)
            else:
                # copy files
                shutil.copyfile(src, dest)
        # cross platform & also catches permission errors
        except (OSError, IOError) as err:
            # err.args is a tuple (err_code, err_message)
            die(1, f"Copy Error: {err.args[1]} : {src} => {dest}")
    else:
        for path in (src, dest):
            if not Path(path) and path == src:
                bad_path = 'src'
            elif not Path(path) and path == dest:
                bad_path = 'dest'
            print(f"Path Error: {bad_path}: {path}")


def delete_dirs_or_files(path_to_delete):
    """ Delete files or folders

    Args:
        path_to_delete (Path): file or dir to delete
    """
    # remove file
    try:
        if Path(path_to_delete).is_file():
            Path(path_to_delete).unlink()
        else:
            # remove dir
            shutil.rmtree(path_to_delete)

    # cross platform & also catches permission errors
    except (OSError, IOError) as err:
        # err.args is a tuple (err_code, err_message)
        print('Error:', err.args[1], ':', path_to_delete)

    print('\nDeleted:', path_to_delete)


def clear_console():
    """ Cross Platform convenience function to clear the console
    """
    if platform.system() == "Windows":
        subprocess.call('cls', shell=True)
    else:
        subprocess.call('clear', shell=True)