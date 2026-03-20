/**
 * Pre-flight validators for Tripletex API calls.
 * Catches missing required fields BEFORE hitting the API to avoid 4xx errors.
 * Returns null if valid, or an error string if invalid.
 */

type Validator = (body: Record<string, unknown>, params?: Record<string, string>) => string | null;

const requireFields = (fields: string[], body: Record<string, unknown>): string | null => {
  const missing = fields.filter((f) => {
    if (f.includes(".")) {
      const [parent, child] = f.split(".");
      const obj = body[parent] as Record<string, unknown> | undefined;
      return !obj || obj[child] === undefined || obj[child] === null;
    }
    return body[f] === undefined || body[f] === null || body[f] === "";
  });
  if (missing.length > 0) return `Missing required fields: ${missing.join(", ")}`;
  return null;
};

// POST validators keyed by path pattern
const postValidators: Record<string, Validator> = {
  "/employee": (body) => {
    const err = requireFields(["firstName", "lastName", "department.id"], body);
    if (err) return err;
    const userType = body.userType as string | undefined;
    if (!userType || userType === "" || userType === "0") {
      return 'userType is required. Use "NO_ACCESS" or "STANDARD" (never empty/0)';
    }
    if (userType === "ADMINISTRATOR") {
      return 'userType "ADMINISTRATOR" is not valid. Use "NO_ACCESS" or "STANDARD"';
    }
    return null;
  },

  "/customer": (body) => {
    const err = requireFields(["name"], body);
    if (err) return err;
    if (!body.isCustomer && !body.isSupplier) {
      return "Must set isCustomer: true (for customers) or isSupplier: true (for suppliers)";
    }
    return null;
  },

  "/product": (body) => requireFields(["name"], body),

  "/department": (body) => requireFields(["name"], body),

  "/order": (body) => {
    const err = requireFields(["customer.id", "orderDate", "deliveryDate"], body);
    if (err) return err;
    return null;
  },

  "/order/orderline": (body) => {
    const err = requireFields(["order.id"], body);
    if (err) return err;
    return null;
  },

  "/invoice": (body) => {
    const err = requireFields(["invoiceDate", "invoiceDueDate", "orders"], body);
    if (err) return err;
    const orders = body.orders as unknown[];
    if (!Array.isArray(orders) || orders.length === 0) {
      return "orders must be a non-empty array of {id} objects";
    }
    return null;
  },

  "/travelExpense": (body) => requireFields(["employee.id", "title", "date"], body),

  "/travelExpense/cost": (body) => {
    const err = requireFields(["travelExpense.id", "costCategory.id", "paymentType.id", "date", "amountCurrencyIncVat"], body);
    if (err) return err;
    return null;
  },

  "/project": (body) => requireFields(["name"], body),

  "/contact": (body) => requireFields(["firstName", "lastName", "customer.id"], body),

  "/timesheet/entry": (body) => requireFields(["employee.id", "project.id", "activity.id", "date", "hours"], body),
};

// PUT validators keyed by path pattern
const putValidators: Record<string, Validator> = {
  // Generic PUT: must have id and version
  __default: (body) => {
    // Skip for action endpoints like /:payment, /:createCreditNote
    return null;
  },
};

export function validatePost(path: string, body: Record<string, unknown>): string | null {
  // Exact match first
  if (postValidators[path]) return postValidators[path](body, undefined);
  // Try without trailing segments for nested paths
  for (const [pattern, validator] of Object.entries(postValidators)) {
    if (path === pattern || path.startsWith(pattern + "/")) {
      return validator(body, undefined);
    }
  }
  return null;
}

export function validatePut(path: string, body: Record<string, unknown>): string | null {
  // Action endpoints (/:payment, /:createCreditNote) - no body validation needed
  if (path.includes("/:")) return null;

  // Regular PUT updates need id and version
  if (body && Object.keys(body).length > 0) {
    if (body.id === undefined) return "PUT requires 'id' in body";
    if (body.version === undefined) return "PUT requires 'version' in body (from GET response)";
  }
  return null;
}
