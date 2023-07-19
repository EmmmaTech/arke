Internals
=========

These are utilities that Arke uses internally. It is not recommended to use these, but they are documented anyways for completeness.

AsyncIO Utilities
-----------------

.. autofunction:: arke.internal.async_utils.completed_future

.. autofunction:: arke.internal.async_utils.gather_optionally

JSON
----

.. autodata:: arke.internal.json.JSONable

.. autofunction:: arke.internal.json.load_json_serializers

Ratelimits
----------

.. autoclass:: arke.internal.ratelimit.Lock
    :members:

.. autoclass:: arke.internal.ratelimit.TimePer
    :members:
