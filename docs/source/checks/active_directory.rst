Active Directory
^^^^^^^^^^^^^^^^
Uses ldapsearch to authenticate against Active Directory and query user entries.

`Uses Accounts`

Custom Properties:

.. list-table::
   :widths: 25 50

   * - domain
     - UPN suffix for the account (Ex: example.com)
   * - base_dn
     - base DN value of the domain (Ex: dc=example,dc=com)
