from __future__ import annotations

import ast

from boneio.message_bus.basic import MessageBus
from boneio.modbus.sensor.base import BaseSensor
from boneio.config import Config


class ModbusDerivedNumericSensor(BaseSensor):
    def __init__(
        self,
        name: str,
        parent: dict,
        unit_of_measurement: str,
        state_class: str,
        device_class: str,
        value_type: str,
        return_type: str,
        filters: list,
        message_bus: MessageBus,
        formula: str,
        context_config: dict,
        config: Config,
        source_sensor_base_address: str,
        source_sensor_decoded_name: str,
        user_filters: list | None = [],
        ha_filter: str = "round(2)",
    ) -> None:
        BaseSensor.__init__(
            self,
            name=name,
            parent=parent,
            unit_of_measurement=unit_of_measurement,
            state_class=state_class,
            device_class=device_class,
            value_type=value_type,
            return_type=return_type,
            filters=filters,
            message_bus=message_bus,
            config=config,
            user_filters=user_filters,
            ha_filter=ha_filter,
        )
        self._formula = formula
        self._context_config = context_config
        self._source_sensor_base_address = source_sensor_base_address
        self._source_sensor_decoded_name = source_sensor_decoded_name

    @property
    def formula(self) -> str:
        return self._formula

    @property
    def context(self) -> dict:
        return self._context_config

    @property
    def base_address(self) -> str:
        return self._source_sensor_base_address

    @property
    def state(self) -> float:
        """Give rounded value of temperature."""
        return self._value or 0.0

    @property
    def source_sensor_decoded_name(self) -> str:
        return self._source_sensor_decoded_name

    def _safe_evaluate_expression(self, formula: str, context: dict) -> float:
        """
        Safely evaluate mathematical expressions without using eval().
        Supports basic arithmetic operations and common mathematical functions.
        """
        import logging

        # Replace variables in the formula with their values
        formula_with_values = formula
        for var, value in context.items():
            formula_with_values = formula_with_values.replace(var, str(value))

        # Try to parse as a simple literal first
        try:
            return float(ast.literal_eval(formula_with_values))
        except (ValueError, SyntaxError):
            pass

        # For more complex expressions, use a limited AST-based evaluator
        try:
            tree = ast.parse(formula, mode="eval")
            return self._evaluate_ast_node(tree.body, context)
        except Exception as e:
            logging.error(f"Failed to evaluate formula '{formula}': {e}")
            # Return the original sensor value if evaluation fails
            return context.get("X", 0.0)

    def _evaluate_ast_node(self, node: ast.AST, context: dict) -> float:
        """Safely evaluate AST nodes for mathematical expressions."""
        if isinstance(node, ast.Constant):
            return float(node.value)
        elif isinstance(node, ast.Name):
            if node.id in context:
                return float(context[node.id])
            else:
                raise ValueError(f"Unknown variable: {node.id}")
        elif isinstance(node, ast.BinOp):
            left = self._evaluate_ast_node(node.left, context)
            right = self._evaluate_ast_node(node.right, context)

            if isinstance(node.op, ast.Add):
                return left + right
            elif isinstance(node.op, ast.Sub):
                return left - right
            elif isinstance(node.op, ast.Mult):
                return left * right
            elif isinstance(node.op, ast.Div):
                if right == 0:
                    raise ValueError("Division by zero")
                return left / right
            elif isinstance(node.op, ast.Pow):
                return left**right
            elif isinstance(node.op, ast.Mod):
                return left % right
            else:
                raise ValueError(f"Unsupported operation: {type(node.op)}")
        elif isinstance(node, ast.UnaryOp):
            operand = self._evaluate_ast_node(node.operand, context)
            if isinstance(node.op, ast.UAdd):
                return operand
            elif isinstance(node.op, ast.USub):
                return -operand
            else:
                raise ValueError(f"Unsupported unary operation: {type(node.op)}")
        elif isinstance(node, ast.Call):
            # Support common mathematical functions
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
                args = [self._evaluate_ast_node(arg, context) for arg in node.args]

                if func_name == "abs" and len(args) == 1:
                    return abs(args[0])
                elif func_name == "round" and len(args) in [1, 2]:
                    if len(args) == 1:
                        return round(args[0])
                    else:
                        return round(args[0], int(args[1]))
                elif func_name == "min" and len(args) >= 1:
                    return min(args)
                elif func_name == "max" and len(args) >= 1:
                    return max(args)
                elif func_name == "pow" and len(args) == 2:
                    return pow(args[0], args[1])
                elif func_name == "int" and len(args) == 1:
                    return int(args[0])
                elif func_name == "float" and len(args) == 1:
                    return float(args[0])
                else:
                    raise ValueError(f"Unsupported function: {func_name}")
            else:
                raise ValueError("Only simple function calls are supported")
        else:
            raise ValueError(f"Unsupported AST node type: {type(node)}")

    def evaluate_state(
        self, source_sensor_value: int | float, timestamp: float
    ) -> None:
        context = {
            "X": source_sensor_value,
            **self.context,
        }

        # Use safe evaluation method without eval()
        try:
            value = self._safe_evaluate_expression(self.formula, context)
        except Exception as e:
            # If evaluation fails, log the error and use the original value
            import logging

            logging.error(f"Formula evaluation failed for {self.name}: {e}")
            value = source_sensor_value

        self.set_value(value, timestamp)
