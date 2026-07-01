"""
Role-based access configuration.

This is the single source of truth for what each role is allowed to see.
Two layers of restriction, both enforced server-side (never trust the
LLM to "behave" -- it only ever sees what we choose to show it, and
everything it outputs is re-checked before it touches the database):

1. allowed_tables: which tables the LLM is told about, AND which tables
   the generated SQL is allowed to reference at all. None = no
   restriction (sees/can query every table).

2. row_filter_column: if set, every allowed table gets an automatic
   "WHERE <row_filter_column> = <donor_id>" wrapped around it before
   execution, so a donor only ever sees rows belonging to them --
   even if the LLM "forgets" to add that condition itself.
"""

ROLES = {
    "admin": {
        "label": "Admin (full access)",
        "allowed_tables": None,       # None = every table in the DB
        "row_filter_column": None,    # None = no row-level restriction
        "requires_donor_id": False,
    },
    "donor": {
        "label": "Donor (self-service)",
        # Only these tables exist as far as the LLM/SQL is concerned.
        "allowed_tables": ["Donors", "Donations", "Sponsorships", "EventDonations"],
        # Every one of the tables above has a DonorId column linking it
        # back to a specific donor -- that's what we filter on.
        "row_filter_column": "DonorId",
        "requires_donor_id": True,
    },
}


def get_role(role_name):
    """Returns the role config dict, or None if the role doesn't exist."""
    return ROLES.get(role_name)
