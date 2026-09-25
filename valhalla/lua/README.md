Mountpoint only. compose.yaml binds `./lua` over this directory at `/conf/lua`
inside the read-only `./valhalla:/conf` bind, and Docker cannot create a
mountpoint in a read-only bind, so the directory has to exist in the checkout.
Its contents are never seen by a container.
