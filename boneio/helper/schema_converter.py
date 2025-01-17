from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Union

import yaml
from yaml import SafeLoader, load


class BoneIOLoader(SafeLoader):
    """Custom YAML loader with !include constructor."""
    
    def __init__(self, stream):
        self._root = os.path.split(stream.name)[0]
        super().__init__(stream)
    
    def include(self, node):
        """Include file referenced at node."""
        filename = os.path.join(self._root, self.construct_scalar(node))
        with open(filename, 'r') as f:
            return load(f, BoneIOLoader)

# Register the !include constructor
BoneIOLoader.add_constructor('!include', BoneIOLoader.include)

def convert_type(cerberus_type: Union[str, List[str]]) -> Union[str, List[str]]:
    """Convert Cerberus type to JSON Schema type."""
    
        
    type_map = {
        'string': 'string',
        'integer': 'integer',
        'float': 'number',
        'boolean': 'boolean',
        'dict': 'object',
        'list': 'array'
    }
    if isinstance(cerberus_type, list):
        return [type_map.get(type, 'string') for type in cerberus_type]
    return type_map.get(cerberus_type, 'string')

def create_boolean_schema() -> Dict[str, Any]:
    """Create a schema that accepts both boolean and boolean-like string values."""
    return {
        "oneOf": [
            {"type": "boolean"},
            {
                "type": "string",
                "enum": ["yes", "no", "true", "false", "on", "off"],
                "x-yaml-boolean": True
            }
        ]
    }

def convert_cerberus_to_json_schema(cerberus_schema: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a Cerberus schema to JSON Schema format."""
    json_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {},
        "required": []
    }

    for field, schema in cerberus_schema.items():
        if not isinstance(schema, dict):
            continue

        field_schema = {}

        # Handle type conversion, nullable and !include
        if "type" in schema:
            if schema["type"] == "boolean":
                field_schema.update(create_boolean_schema())
            else:
                base_type = convert_type(schema["type"])
                types = ["string"]  # Always allow string for !include
                if isinstance(base_type, list):
                    types.extend(base_type)
                else:
                    types.append(base_type)
                if schema.get("nullable", False):
                    types.append("null")
                field_schema["type"] = types

        # Handle required fields - only if required and no default
        if schema.get("required", False) and "default" not in schema:
            json_schema["required"].append(field)

        # Handle default values
        if "default" in schema:
            field_schema["default"] = schema["default"]

        # Handle nested dictionaries and arrays
        if "schema" in schema and isinstance(schema["schema"], dict):
            if schema.get("type") == "dict":
                types = ["string", "object"]  # Allow both string for !include and object
                if schema.get("nullable", False):
                    types.append("null")
                field_schema["type"] = types
                field_schema["properties"] = {}
                nested_required = []
                
                for nested_field, nested_schema in schema["schema"].items():
                    field_schema["properties"][nested_field] = convert_cerberus_to_json_schema(
                        {nested_field: nested_schema}
                    )["properties"][nested_field]
                    # Only add to required if the field is required and has no default
                    if nested_schema.get("required", False) and "default" not in nested_schema:
                        nested_required.append(nested_field)
                
                if nested_required:
                    field_schema["required"] = nested_required
                    
            elif schema.get("type") == "list":
                types = ["string", "array"]  # Allow both string for !include and array
                if schema.get("nullable", False):
                    types.append("null")
                field_schema["type"] = types
                if isinstance(schema["schema"], dict):
                    field_schema["items"] = convert_cerberus_to_json_schema(
                        {"item": schema["schema"]}
                    )["properties"]["item"]

        # Handle allowed values (enum)
        if "allowed" in schema:
            if schema.get("type") == "list":
                if "items" not in field_schema:
                    field_schema["items"] = {}
                field_schema["items"]["enum"] = schema["allowed"]
                # Add examples for better IDE support
                field_schema["items"]["examples"] = [schema["allowed"][0]] if schema["allowed"] else []
            else:
                field_schema["enum"] = schema["allowed"]
                # Add examples for better IDE support
                field_schema["examples"] = [schema["allowed"][0]] if schema["allowed"] else []

        # Handle descriptions from meta
        if "meta" in schema and isinstance(schema["meta"], dict):
            if "label" in schema["meta"]:
                field_schema["description"] = schema["meta"]["label"]
                # Add title for better IDE support
                field_schema["title"] = field.replace("_", " ").capitalize()

        json_schema["properties"][field] = field_schema

    # Remove required array if empty
    if not json_schema["required"]:
        del json_schema["required"]

    return json_schema

def generate_section_schema(section_name: str, section_schema: Dict[str, Any]) -> Dict[str, Any]:
    """Generate a schema for a specific section."""
    if section_schema.get("type") == "array":
        # For array types, use the items schema directly
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            **convert_cerberus_to_json_schema({section_name: section_schema})["properties"][section_name]
        }
    else:
        # For object types, wrap in an object schema
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                section_name: convert_cerberus_to_json_schema({section_name: section_schema})["properties"][section_name]
            }
        }

def main():
    """Main function to convert schema."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    schema_file = os.path.join(script_dir, "..", "schema", "schema.yaml")
    output_dir = os.path.join(script_dir, "..", "webui", "schema")
    
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    # Load the schema
    with open(schema_file, "r") as f:
        schema = yaml.load(f, Loader=BoneIOLoader)
    
    # Convert and save the main schema
    json_schema = convert_cerberus_to_json_schema(schema)
    main_schema_file = os.path.join(output_dir, "config.schema.json")
    with open(main_schema_file, "w") as f:
        json.dump(json_schema, f, indent=2)
    print(f"Schema written to {main_schema_file}")
    
    # Generate and save section-specific schemas
    for section_name, section_schema in schema.items():
        section_json_schema = generate_section_schema(section_name, section_schema)
        section_schema_file = os.path.join(output_dir, f"{section_name}.schema.json")
        with open(section_schema_file, "w") as f:
            json.dump(section_json_schema, f, indent=2)
        print(f"Section schema for {section_name} written to {section_schema_file}")

if __name__ == "__main__":
    main()
