import fnmatch
import logging
import os
import re
from collections import OrderedDict
from typing import Any, Tuple

from cerberus import TypeDefinition, Validator
from yaml import MarkedYAMLError, SafeLoader, YAMLError, load

from boneio.const import ID, OUTPUT
from boneio.helper.exceptions import ConfigurationException
from boneio.helper.timeperiod import TimePeriod

schema_file = os.path.join(os.path.dirname(__file__), "../schema/schema.yaml")
_LOGGER = logging.getLogger(__name__)

SECRET_YAML = "secrets.yaml"
_SECRET_VALUES = {}


class BoneIOLoader(SafeLoader):
    """Loader which support for include in yaml files."""

    def __init__(self, stream):

        self._root = os.path.split(stream.name)[0]

        super(BoneIOLoader, self).__init__(stream)

    def include(self, node):

        filename = os.path.join(self._root, self.construct_scalar(node))

        with open(filename, "r") as f:
            return load(f, BoneIOLoader)

    def _rel_path(self, *args):
        return os.path.join(self._root, *args)

    def construct_secret(self, node):
        secrets = load_yaml_file(self._rel_path(SECRET_YAML))
        if node.value not in secrets:
            raise MarkedYAMLError(
                f"Secret '{node.value}' not defined", node.start_mark
            )
        val = secrets[node.value]
        _SECRET_VALUES[str(val)] = node.value
        return val

    def represent_stringify(self, value):
        return self.represent_scalar(
            tag="tag:yaml.org,2002:str", value=str(value)
        )

    def construct_include_dir_list(self, node):
        files = filter_yaml_files(
            _find_files(self._rel_path(node.value), "*.yaml")
        )
        return [load_yaml_file(f) for f in files]

    def construct_include_dir_merge_list(self, node):
        files = filter_yaml_files(
            _find_files(self._rel_path(node.value), "*.yaml")
        )
        merged_list = []
        for fname in files:
            loaded_yaml = load_yaml_file(fname)
            if isinstance(loaded_yaml, list):
                merged_list.extend(loaded_yaml)
        return merged_list

    def construct_include_dir_named(self, node):
        files = filter_yaml_files(
            _find_files(self._rel_path(node.value), "*.yaml")
        )
        mapping = OrderedDict()
        for fname in files:
            filename = os.path.splitext(os.path.basename(fname))[0]
            mapping[filename] = load_yaml_file(fname)
        return mapping

    def construct_include_dir_merge_named(self, node):
        files = filter_yaml_files(
            _find_files(self._rel_path(node.value), "*.yaml")
        )
        mapping = OrderedDict()
        for fname in files:
            loaded_yaml = load_yaml_file(fname)
            if isinstance(loaded_yaml, dict):
                mapping.update(loaded_yaml)
        return mapping

    def construct_include_files(self, node):
        files = os.path.join(self._root, self.construct_scalar(node)).split()
        merged_list = []
        for fname in files:
            loaded_yaml = load_yaml_file(fname.strip())
            if isinstance(loaded_yaml, list):
                merged_list.extend(loaded_yaml)
        return merged_list


BoneIOLoader.add_constructor("!include", BoneIOLoader.include)
BoneIOLoader.add_constructor("!secret", BoneIOLoader.construct_secret)
BoneIOLoader.add_constructor(
    "!include_dir_list", BoneIOLoader.construct_include_dir_list
)
BoneIOLoader.add_constructor(
    "!include_dir_merge_list", BoneIOLoader.construct_include_dir_merge_list
)
BoneIOLoader.add_constructor(
    "!include_dir_named", BoneIOLoader.construct_include_dir_named
)
BoneIOLoader.add_constructor(
    "!include_dir_merge_named", BoneIOLoader.construct_include_dir_merge_named
)
BoneIOLoader.add_constructor(
    "!include_files", BoneIOLoader.construct_include_files
)


def filter_yaml_files(files):
    return [
        f
        for f in files
        if (
            os.path.splitext(f)[1] in (".yaml", ".yml")
            and os.path.basename(f) not in ("secrets.yaml", "secrets.yml")
            and not os.path.basename(f).startswith(".")
        )
    ]


def _is_file_valid(name):
    """Decide if a file is valid."""
    return not name.startswith(".")


def _find_files(directory, pattern):
    """Recursively load files in a directory."""
    for root, dirs, files in os.walk(directory, topdown=True):
        dirs[:] = [d for d in dirs if _is_file_valid(d)]
        for basename in files:
            if _is_file_valid(basename) and fnmatch.fnmatch(basename, pattern):
                filename = os.path.join(root, basename)
                yield filename


def load_yaml_file(filename: str) -> Any:
    with open(filename, "r") as stream:
        try:
            return load(stream, Loader=BoneIOLoader) or OrderedDict()
        except YAMLError as exception:
            msg = ""
            if hasattr(exception, "problem_mark"):
                mark = exception.problem_mark
                msg = f" at line {mark.line + 1} column {mark.column + 1}"
            raise ConfigurationException(f"Error loading yaml{msg}") from exception


def get_board_config_path(board_name: str, version: str) -> str:
    """Get the appropriate board configuration file path based on version."""
    base_dir = os.path.join(os.path.dirname(__file__), "../boards")
    version_dir = os.path.join(base_dir, version)
    version_specific_file = os.path.join(version_dir, f"{board_name}.yaml")
    
    if not os.path.exists(version_dir):
        raise ConfigurationException(
            f"Board configurations for version {version} not found. "
            f"Expected directory: {version_dir}"
        )
    
    if os.path.exists(version_specific_file):
        return version_specific_file
        
    raise ConfigurationException(
        f"Board configuration '{board_name}' for version {version} not found. "
        f"Expected file: {version_specific_file}"
    )


def normalize_board_name(name: str) -> str:
    """Normalize board name to a standard format.
    
    Examples:
        32x10a, 32x10A, 32 -> 32_10
        cover -> cover
        cover mix, cm -> cover_mix
        24x16A, 24x16, 24 -> 24_16
    """
    if not name:
        return name

    name = name.lower().strip()
    
    # Handle cover mix variations
    if name in ('cm', 'cover mix', 'covermix', "cover_mix"):
        return 'cover_mix'
    
    # Handle simple cover case
    if name == 'cover':
        return 'cover'
    
    # Handle 32x10A variations
    if name.startswith('32'):
        return '32_10'
    
    # Handle 24x16A variations
    if name.startswith('24'):
        return '24_16'
    
    return name


def merge_board_config(config: dict) -> dict:
    """Merge predefined board configuration with user config."""
    if not config.get("boneio", {}).get("device_type"):
        return config

    board_name = normalize_board_name(config["boneio"]["device_type"])
    version = config["boneio"]["version"]
    
    try:
        board_file = get_board_config_path(f"output_{board_name}", version)
        input_file = get_board_config_path("input", version)
        board_config = load_yaml_file(board_file)
        input_config = load_yaml_file(input_file)
        if not board_config:
            raise ConfigurationException(f"Bottom board configuration file {board_file} is empty")
    except FileNotFoundError:
        raise ConfigurationException(
            f"Board configuration for {board_name} version {version} not found"
        )

    # Copy MCP configuration if not already defined
    if "mcp23017" not in config and "mcp23017" in board_config:
        config["mcp23017"] = board_config["mcp23017"]

    # Process outputs
    if "output" in config:
        output_mapping = board_config.get("output_mapping", {})
        for output in config["output"]:
            if "boneio_output" in output:
                boneio_output = output["boneio_output"].lower()
                mapped_output = output_mapping.get(boneio_output)
                if not mapped_output:
                    raise ConfigurationException(
                        f"Output mapping '{output['boneio_output']}' not found in board configuration"
                    )
                # Merge mapped output with user config, preserving user-specified values
                output.update({k: v for k, v in mapped_output.items() if k not in output})
                del output["boneio_output"]
    if "event" or "binary_sensor" in config:
        input_mapping = input_config.get("input_mapping", {})
        for input in config.get("event", []):
            if "boneio_input" in input:
                boneio_input = input["boneio_input"].lower()
                mapped_input = input_mapping.get(boneio_input)
                if not mapped_input:
                    raise ConfigurationException(
                        f"Input mapping '{input['boneio_input']}' not found in board configuration"
                    )
                # Merge mapped output with user config, preserving user-specified values
                input.update({k: v for k, v in mapped_input.items() if k not in input})

        for input in config.get("binary_sensor", []):
            if "boneio_input" in input:
                boneio_input = input["boneio_input"].lower()
                mapped_input = input_mapping.get(boneio_input)
                if not mapped_input:
                    raise ConfigurationException(
                        f"Input mapping '{input['boneio_input']}' not found in board configuration"
                    )
                # Merge mapped output with user config, preserving user-specified values
                input.update({k: v for k, v in mapped_input.items() if k not in input})


    return config


def one_of(*values, **kwargs):
    """Validate that the config option is one of the given values.
    :param values: The valid values for this type
    """
    options = ", ".join(f"'{x}'" for x in values)

    def validator(value):
        if value not in values:
            import difflib

            options_ = [str(x) for x in values]
            option = str(value)
            matches = difflib.get_close_matches(option, options_)
            if matches:
                matches_str = ", ".join(f"'{x}'" for x in matches)
                raise ConfigurationException(
                    f"Unknown value '{value}', did you mean {matches_str}?"
                )
            raise ConfigurationException(
                f"Unknown value '{value}', valid options are {options}."
            )
        return value

    return validator


timeperiod_type = TypeDefinition("timeperiod", (TimePeriod,), ())


class CustomValidator(Validator):
    """Custom validator of cerberus"""

    types_mapping = Validator.types_mapping.copy()
    types_mapping["timeperiod"] = timeperiod_type

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.allow_unknown = True

    def _validate_case_insensitive(self, case_insensitive, field, value):
        """Validate field allowing any case but check against lowercase values.
        
        The rule's arguments are validated against this schema:
        {'type': 'boolean'}
        """
        if not isinstance(value, str):
            self._error(field, "must be a string")
            return

        allowed = self.schema[field].get('allowed')
        if allowed and value.lower() not in [a.lower() for a in allowed]:
            self._error(field, f"unallowed value {value}")

    def _validate_required_if(self, required_if, field, value):
        """Validate that a field is required if a condition is met.
        
        The rule's arguments are validated against this schema:
        {'type': 'dict'}
        """
        if not required_if:
            return

        for key, values in required_if.items():
            if key not in self.document:
                continue

            doc_value = self.document[key]
            if isinstance(doc_value, str):
                doc_value = doc_value.lower()
            if doc_value in [v.lower() if isinstance(v, str) else v for v in values]:
                if field not in self.document:
                    self._error(field, f"required when {key} is {doc_value}")

    def _validate_forbidden_if(self, forbidden_if, field, value):
        """Validate that a field is forbidden if a condition is met.
        
        The rule's arguments are validated against this schema:
        {'type': 'dict'}
        """
        if not forbidden_if:
            return
        default_value = self.schema[field].get("default")
        for key, values in forbidden_if.items():
            if key not in self.document:
                continue

            doc_value = self.document[key]
            if isinstance(doc_value, str):
                doc_value = doc_value.lower()
            
            if doc_value in [v.lower() if isinstance(v, str) else v for v in values]:
                if field in self.document and value != default_value:
                    self._error(field, f"forbidden when {key} is {doc_value}")

    def _normalize_coerce_action_field(self, value):
        """Handle conditional defaults for action fields."""
        action = self.document.get('action', '').lower()
        field_name = self.schema_path[-1]
        if value is None:
            if (field_name == 'action_cover' and action == 'cover') or \
               (field_name == 'action_output' and action == 'output'):
                return 'TOGGLE'
            return None
        return str(value).upper()

    def _normalize_coerce_lower(self, value):
        """Convert string to lowercase."""
        if isinstance(value, str):
            return value.lower()
        return value

    def _normalize_coerce_upper(self, value):
        """Convert string to uppercase."""
        if isinstance(value, str):
            return value.upper()
        return value

    def _normalize_coerce_str(self, value):
        """Convert value to string."""
        return str(value)

    def _normalize_coerce_actions_output(self, value):
        return str(value).upper()

    def _normalize_coerce_positive_time_period(self, value) -> TimePeriod:
        """Validate and transform time period with time unit and integer value."""
        if isinstance(value, int):
            raise ConfigurationException(
                f"Don't know what '{value}' means as it has no time *unit*! Did you mean '{value}s'?"
            )
        if isinstance(value, TimePeriod):
            value = str(value)
        if not isinstance(value, str):
            raise ConfigurationException(
                "Expected string for time period with unit."
            )

        unit_to_kwarg = {
            "us": "microseconds",
            "microseconds": "microseconds",
            "ms": "milliseconds",
            "milliseconds": "milliseconds",
            "s": "seconds",
            "sec": "seconds",
            "secs": "seconds",
            "seconds": "seconds",
            "min": "minutes",
            "mins": "minutes",
            "minutes": "minutes",
            "h": "hours",
            "hours": "hours",
            "d": "days",
            "days": "days",
        }

        match = re.match(r"^([-+]?[0-9]*\.?[0-9]*)\s*(\w*)$", value)
        if match is None:
            raise ConfigurationException(
                f"Expected time period with unit, got {value}"
            )
        kwarg = unit_to_kwarg[one_of(*unit_to_kwarg)(match.group(2))]
        return TimePeriod(**{kwarg: float(match.group(1))})

    def _lookup_field(self, path: str) -> Tuple:
        """
        Implement relative paths with dot (.) notation, following Python
        guidelines: https://www.python.org/dev/peps/pep-0328/#guido-s-decision
        - A single leading dot indicates a relative import
        starting with the current package.
        - Two or more leading dots give a relative import to the parent(s)
        of the current package, one level per dot after the first
        Return: Tuple(dependency_name: str, dependency_value: Any)
        """
        # Python relative imports use a single leading dot
        # for the current level, however no dot in Cerberus
        # does the same thing, thus we need to check 2 or more dots
        if path.startswith(".."):
            parts = path.split(".")
            dot_count = path.count(".")
            context = self.root_document

            for key in self.document_path[:dot_count]:
                context = context[key]

            context = context.get(parts[-1])

            return parts[-1], context

        else:
            return super()._lookup_field(path)

    def _check_with_output_id_uniqueness(self, field, value):
        """Check if outputs ids are unique if they exists."""
        if self.document[OUTPUT] is not None:
            all_ids = [x[ID] for x in self.document[OUTPUT]]
            if len(all_ids) != len(set(all_ids)):
                self._error(field, "Output IDs are not unique.")

    def _normalize_coerce_to_bool(self, value):
        return True

    def _normalize_coerce_remove_space(self, value):
        return str(value).replace(" ", "")

    def _normalize_coerce_actions_output(self, value):
        return str(value).upper()


def load_config_from_string(config_str: str) -> dict:
    """Load config from string."""
    schema = load_yaml_file(schema_file)
    v = CustomValidator(schema, purge_unknown=True)

    if not v.validate(config_str):
        error_msg = "Configuration validation failed:\n"
        for field, errors in v.errors.items():
            error_lines = []
            if "line" in v.errors[field][0]:
                error_lines = [
                    f"{v.errors[field][0]['line']+1}: {line}"
                    for line in config_str.splitlines()[v.errors[field][0]["line"]-1:v.errors[field][0]["line"]+1]
                ]
            error_msg += f"\n- {field}: {errors}\n{', '.join(error_lines)}"
        raise ConfigurationException(error_msg)
    doc = v.normalized(v.document, always_return_document=True)
    return merge_board_config(doc)


def load_config_from_file(config_file: str):
    try:
        config_yaml = load_yaml_file(config_file)
    except FileNotFoundError as err:
        raise ConfigurationException(err)
    if not config_yaml:
        _LOGGER.warning("Missing yaml file. %s", config_file)
        return None
    return load_config_from_string(config_yaml)
