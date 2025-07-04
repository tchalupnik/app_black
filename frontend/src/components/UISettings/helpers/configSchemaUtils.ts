// Utility functions for config schema processing

import { RJSFSchema } from "@rjsf/utils";

// Rozszerzamy interfejs JSONSchema7 o właściwości specyficzne dla naszej aplikacji
interface ExtendedJSONSchema extends RJSFSchema {
  'x-timeperiod'?: boolean;
  properties?: { [key: string]: ExtendedJSONSchema };
  items?: ExtendedJSONSchema | ExtendedJSONSchema[];
}

/**
 * Bezpieczne sprawdzenie czy schemat jest obiektem ExtendedJSONSchema i ma właściwość properties
 */
function hasProperties(schema: any): schema is ExtendedJSONSchema {
  return schema && typeof schema === 'object' && 'properties' in schema;
}

/**
 * Bezpieczna konwersja schematu do ExtendedJSONSchema
 */
function asExtendedSchema(schema: any): ExtendedJSONSchema | undefined {
  if (!schema || typeof schema !== 'object') return undefined;
  return schema as ExtendedJSONSchema;
}

 /**
   * Convert milliseconds back to string format for backend
   */
 const convertMillisecondsToTimeperiod = (milliseconds: number): string => {
    if (milliseconds < 1000) {
      return `${milliseconds}ms`;
    } else if (milliseconds < 60000) {
      return `${milliseconds / 1000}s`;
    } else if (milliseconds < 3600000) {
      return `${milliseconds / 60000}m`;
    } else {
      return `${milliseconds / 3600000}h`;
    }
  };



  /**
   * Convert timeperiod object to milliseconds for form display
   */
  export const convertTimeperiodToMilliseconds = (timeperiodObj: any): number => {
    if (typeof timeperiodObj === 'number') return timeperiodObj;
    if (typeof timeperiodObj === 'string') {
      // Parse string like "120ms" or "30s"
      const match = timeperiodObj.match(/^(\d+(?:\.\d+)?)(ms|s|m|h)?$/);
      if (match) {
        const value = parseFloat(match[1]);
        const unit = match[2] || 'ms';
        switch (unit) {
          case 'ms': return value;
          case 's': return value * 1000;
          case 'm': return value * 60 * 1000;
          case 'h': return value * 60 * 60 * 1000;
          default: return value;
        }
      }
      return 0;
    }
    if (timeperiodObj && typeof timeperiodObj === 'object') {
      // Use milliseconds from timeperiod object
      return timeperiodObj.milliseconds || timeperiodObj._total_in_seconds * 1000 || 0;
    }
    return 0;
  };

  /**
   * Convert form data back to original types based on original data and schema
   */
  export const convertFormDataToOriginalTypes = (formData: any, originalData: any, schema?: RJSFSchema | ExtendedJSONSchema): any => {
    // Konwertujemy schema do ExtendedJSONSchema
    const extendedSchema = asExtendedSchema(schema);
    console.log("convertFormDataToOriginalTypes", formData, originalData, schema)
    if (!originalData || typeof originalData !== 'object') return formData;
    if (!formData || typeof formData !== 'object') return formData;

    const converted = { ...formData };
    
    // Przetwarzamy wszystkie klucze z formData, nie tylko z originalData
    // aby uwzględnić nowe pola dodane w formularzu
    Object.keys(converted).forEach(key => {
      const currentValue = converted[key];
      const originalValue = originalData[key];
      const propSchema = extendedSchema?.properties?.[key];
      
      // Jeśli klucz nie istnieje w originalData, zachowujemy wartość z formularza
      if (originalValue === undefined || originalValue === null) {
        return;
      }
      
      const originalType = typeof originalValue;
      
      // Handle array with items schema
      if (Array.isArray(currentValue)) {
        // Sprawdzamy czy schema ma definicję items
        if (propSchema && typeof propSchema === 'object' && propSchema.items) {
          converted[key] = currentValue.map((item: any, index: number) => {
            // Sprawdzamy czy element jest obiektem i czy mamy odpowiedni schemat
            if (typeof item === 'object' && item !== null) {
              // Jeśli mamy oryginalny element, używamy go jako referencji
              if (Array.isArray(originalValue) && index < originalValue.length && typeof originalValue[index] === 'object') {
                return convertFormDataToOriginalTypes(item, originalValue[index], 
                  typeof propSchema.items === 'object' ? propSchema.items as ExtendedJSONSchema : undefined);
              } 
              // Dla nowych elementów używamy tylko schematu
              else if (typeof propSchema.items === 'object') {
                const itemsSchema = propSchema.items as ExtendedJSONSchema;
                // Konwertujemy pola timeperiod w nowych elementach
                if (hasProperties(itemsSchema) && itemsSchema.properties) {
                  Object.keys(item).forEach(itemKey => {
                    const itemPropSchema = itemsSchema.properties?.[itemKey];
                    
                    if (itemPropSchema && 
                        typeof itemPropSchema === 'object' && 
                        itemPropSchema['x-timeperiod'] === true && 
                        typeof item[itemKey] === 'number') {
                      item[itemKey] = convertMillisecondsToTimeperiod(item[itemKey]);
                    }
                  });
                }
                return item;
              }
            }
            return item;
          });
        }
      }
      // Convert milliseconds back to timeperiod string for backend
      else if (propSchema && 
               typeof propSchema === 'object' && 
               propSchema['x-timeperiod'] === true && 
               typeof currentValue === 'number') {
        console.log(`Converting timeperiod ${key}: ${currentValue}ms`, propSchema);
        const timeperiodString = convertMillisecondsToTimeperiod(currentValue);
        converted[key] = timeperiodString;
        console.log(`✓ Converted timeperiod ${key}: ${currentValue}ms → ${timeperiodString}`);
      }
      // Convert string back to number if original was number
      else if (originalType === 'number' && typeof currentValue === 'string') {
        const numValue = parseFloat(currentValue);
        if (!isNaN(numValue)) {
          converted[key] = numValue;
        }
      }
      // Handle nested objects recursively
      else if (typeof currentValue === 'object' && currentValue !== null && 
               typeof originalValue === 'object' && originalValue !== null) {
        converted[key] = convertFormDataToOriginalTypes(currentValue, originalValue, 
          propSchema && typeof propSchema === 'object' ? propSchema as ExtendedJSONSchema : undefined);
      }
    });
    
    return converted;
  };


  /**
 * Usuwa z formData:
 * 1. Pola ukryte (ui:widget: "hidden" w uiSchema)
 * 2. Pola o wartości domyślnej (zdefiniowanej w schema)
 *
 * @param formData - Dane formularza przekazywane przez RJSF
 * @param schema - JSON Schema sekcji
 * @param uiSchema - uiSchema sekcji
 * @returns Nowy obiekt bez ukrytych pól i pól z wartością domyślną
 */
export const stripHiddenAndDefaults = (
    formData: any,
    schema: any,
    uiSchema: any = {}
  ): any => {
    console.log("stripHiddenAndDefaults", formData, schema, uiSchema)
    
    // Handle arrays
    if (Array.isArray(formData)) {
      const filteredArray = formData
        .map((item) => {
          // For arrays, uiSchema might be structured differently
          const itemUiSchema = uiSchema?.items || uiSchema || {};
          return stripHiddenAndDefaults(item, schema?.items, itemUiSchema);
        })
        .filter((item) => {
          // Keep item if it's not undefined and not an empty object
          if (item === undefined || item === null) return false;
          if (typeof item !== "object") return true;
          if (Array.isArray(item)) return item.length > 0;
          return Object.keys(item).length > 0;
        });
      
      return filteredArray;
    }
    
    // Handle primitives
    if (typeof formData !== "object" || formData === null) {
      return formData;
    }
    
    const result: any = {};
    
    for (const key of Object.keys(formData)) {
      const fieldValue = formData[key];
      const fieldSchema = schema?.properties?.[key];
      const fieldUiSchema = uiSchema?.[key] || {};
      
      // Skip hidden fields
      if (fieldUiSchema["ui:widget"] === "hidden") {
        console.log(`Skipping hidden field: ${key}`);
        continue;
      }
      
      // Skip fields with default values
      const defaultValue = fieldSchema?.default;
      if (defaultValue !== undefined && JSON.stringify(fieldValue) === JSON.stringify(defaultValue)) {
        console.log(`Skipping default value field: ${key} = ${JSON.stringify(defaultValue)}`);
        continue;
      }
      
      // Recursively process nested objects and arrays
      const processedChild = stripHiddenAndDefaults(fieldValue, fieldSchema, fieldUiSchema);
      
      // Include field if it has meaningful content
      if (processedChild !== undefined && processedChild !== null) {
        if (typeof processedChild === "object") {
          if (Array.isArray(processedChild)) {
            if (processedChild.length > 0) {
              result[key] = processedChild;
            }
          } else {
            if (Object.keys(processedChild).length > 0) {
              result[key] = processedChild;
            }
          }
        } else {
          result[key] = processedChild;
        }
      }
    }
    
    return result;
  }