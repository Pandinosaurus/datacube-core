##
## This file is part of the Open Data Cube, see https://opendatacube.org for more information
##
## Copyright (c) 2015-2020 ODC Contributors
## SPDX-License-Identifier: Apache-2.0
##
ARG ORG=opendatacube
ARG V_BASE=3.3.0
ARG V_PG=12
FROM ${ORG}/geobase-builder:${V_BASE} as env_builder

# Set the locale, this is required for some of the Python packages
ENV LC_ALL C.UTF-8

COPY docker/constraints.in /conf/requirements.txt
COPY docker/constraints.txt docker/nobinary.txt /conf/

# build wheels in cached directory to allow re-use even when requirements.txt is changed
# then copy to final location
#   /root/.cache/pip  <-- pip cache
#   /var/cache/wheels <-- downloaded sources and compiled wheels
#   /wheels           <-- final destination copied from /var/cache/wheels cache
RUN --mount=type=cache,target=/root/.cache/pip \
    --mount=type=cache,target=/var/cache/wheels \
    mkdir /wheels \
    && env-build-tool wheels /conf/requirements.txt /conf/constraints.txt /var/cache/wheels \
    && python3 -m pip wheel \
       -r /conf/requirements.txt \
       --find-links /var/cache/wheels \
       --no-index \
       --only-binary=:all: \
       --wheel-dir /wheels


#################################################################################
# Runner stage
#################################################################################
FROM ${ORG}/geobase-runner:${V_BASE}
ARG V_PG

# Set the locale, this is required for some of the Python packages
ENV LC_ALL C.UTF-8
RUN apt-get update \
  && DEBIAN_FRONTEND=noninteractive apt-get install -y --fix-missing --no-install-recommends --allow-change-held-packages \
  # datacube tests need redis
  redis-server \
  # include db for running tests
  postgresql \
  postgresql-client-${V_PG} \
  postgresql-${V_PG} \
  # to become test user
  sudo \
  # git is needed for sdist|bdist_wheel
  git \
  # for docs
  make \
  graphviz \
  && rm -rf /var/lib/apt/lists/*

# if using binary rasterio package, to support https
RUN mkdir -p /etc/pki/tls/certs \
&& ln -s /etc/ssl/certs/ca-certificates.crt /etc/pki/tls/certs/ca-bundle.crt;

# prep db
RUN  install --owner postgres --group postgres -D -d /var/run/postgresql /srv/postgresql \
  && sudo -u postgres "$(find /usr/lib/postgresql/ -type f -name initdb)" -D "/srv/postgresql" --auth-host=md5 --encoding=UTF8

RUN groupadd --gid 1000 odc \
  && useradd --gid 1000 \
  --uid 1000 \
  --create-home \
  --shell /bin/bash -N odc \
  && adduser odc users \
  && adduser odc sudo \
  && echo '%sudo ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers \
  && install -d -o odc -g odc /env \
  && install -d -o odc -g odc /code \
  && true

COPY --from=env_builder /bin/tini /bin/tini
USER odc
RUN --mount=type=bind,from=env_builder,target=/b \
    --mount=type=cache,target=/home/odc/.cache/pip,uid=1000,gid=1000 \
    env-build-tool new_no_index /b/conf/requirements.txt /b/conf/constraints.txt /env /b/wheels

# All steps from above should cache well
# from here down things depend on entire content of code
RUN --mount=type=bind,from=env_builder,target=/b \
    --mount=type=bind,target=/src \
    --mount=type=cache,target=/home/odc/.cache/pip,uid=1000,gid=1000 \
    (cd /src && tar c . ) | (cd /code && tar x) \
    && /env/bin/python -m pip install -e '/code/[all]' --no-index --find-links=/b/wheels \
    && /env/bin/python -m pip install -e /code/examples/io_plugin --no-index --find-links=/b/wheels \
    && /env/bin/python -m pip install -e /code/tests/drivers/fail_drivers --no-index --find-links=/b/wheels

USER root
COPY docker/assets/with_bootstrap /usr/local/bin/

VOLUME /code
WORKDIR /code

ENTRYPOINT ["/bin/tini", "-s", "--", "/usr/local/bin/with_bootstrap"]
