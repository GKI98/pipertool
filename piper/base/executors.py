from abc import abstractmethod, ABC
import os
import time
from typing import Dict
import inspect

import aiohttp
import docker
from pydantic import BaseModel

from piper.base.docker import PythonImage
from piper.base.backend.utils import render_fast_api_backend
from piper.envs import is_docker_env, is_current_env, get_env
from piper.configurations import get_configuration
from piper.utils import docker_utils as du


class BaseExecutor:
    pass


class LocalExecutor:
    pass


def is_known(obj):
    basic = obj.__class__.__name__ in {'dict', 'list', 'tuple', 'str', 'int', 'float', 'bool'}
    models = isinstance(obj, (BaseModel,))
    return basic or models


def prepare(obj):
    if isinstance(obj, (BaseModel,)):
        return obj.dict()
    return obj


def inputs_to_dict(*args, **kwargs):
    from_args = {}
    for arg in args:
        if is_known(arg):
            from_args.update(prepare(arg))
    from_kwargs = {k: prepare(v) for k, v in kwargs.items() if is_known(v)}
    from_args.update(from_kwargs)
    return from_args


class HTTPExecutor(BaseExecutor):

    def __init__(self, host: str, port: int, base_handler: str):
        self.host = host
        self.port = port

    @abstractmethod
    async def run(self, *args, **kwargs):
        pass

    async def __call__(self, *args, **kwargs):
        print(get_env())
        print(is_current_env())
        if is_current_env():
            return await self.run(*args, **kwargs)
        else:
            function = "run"
            request_dict = inputs_to_dict(*args, **kwargs)
            print(request_dict)
            async with aiohttp.ClientSession() as session:
                async with session.post(f'http://{self.host}:{self.port}/{function}', json=request_dict) as resp:
                    return await resp.json()


def copy_piper(path: str):
    cfg = get_configuration()
    from distutils.dir_util import copy_tree
    copy_tree(cfg.piper_path, f"{path}/piper")


def copy_scripts(path: str, scripts: Dict[str, str]):
    for script_name, script_path in scripts.items():
        with open(f"{path}/{script_name}.py", "w") as output:
            with open(script_path, "r") as current_file:
                output.write(current_file.read())


def write_requirements(path, requirements):
    with open(f"{path}/requirements.txt", "w") as output:
        output.write("\n".join(requirements))


def build_image(path: str, docker_image):
    client = docker.DockerClient(base_url='unix://var/run/docker.sock')
    image = docker_image.render()
    with open(f"{path}/Dockerfile", "w") as output:
        output.write(image)

    image, logs = client.images.build(path=path,
                                      tag=docker_image.tag,
                                      quiet=False,
                                      timeout=20)
    for log in logs:
        print(log)
    print(image)


def run_container(image: str, ports: Dict[int, int]):
    client = docker.DockerClient(base_url='unix://var/run/docker.sock')
    container = client.containers.run(image, detach=True, ports=ports)
    for log in container.logs():
        print(log)
    print(container)
    time.sleep(10)

    return container


class FastAPIExecutor(HTTPExecutor):
    requirements = ["gunicorn", "fastapi", "uvicorn", "aiohttp", "docker", "Jinja2", "pydantic", "loguru"]
    base_handler = "run"

    def __init__(self, port: int = 8080, **service_kwargs):
        self.container = None
        self.image_tag = 'piper:latest'
        self.container_name = "piper_FastAPI"

        if is_docker_env():
            docker_client = docker.DockerClient(base_url='unix://var/run/docker.sock')
            cfg = get_configuration()
            project_output_path = cfg.path

            copy_piper(project_output_path)
            copy_scripts(project_output_path, self.scripts())

            self.create_fast_api_files(project_output_path, **service_kwargs)

            # create and run docker container
            # if container exits it will be recreated!
            du.create_image_and_container_by_dockerfile(
                docker_client,
                project_output_path,
                self.image_tag,
                self.container_name,
                port
            )
        else:
            # TODO: Local ENVIRONMENT checks
            pass
        super().__init__('localhost', port, self.base_handler)

    def rm_container(self):
        if self.container:
            self.container.remove(force=True)

    def scripts(self):
        return {"service": inspect.getfile(self.__class__)}

    def create_fast_api_files(self, path: str, **service_kwargs):
        backend = render_fast_api_backend(service_class=self.__class__.__name__,
                                          service_kwargs=dict(service_kwargs),
                                          scripts=self.scripts(),
                                          function_name=self.base_handler,
                                          request_model="StringValue",
                                          response_model="StringValue")

        with open(f"{path}/main.py", "w") as output:
            output.write(backend)

        write_requirements(path, self.requirements)

        gunicorn = "#!/bin/bash \n" \
                   "gunicorn -b 0.0.0.0:8080 --workers 4 main:app --worker-class uvicorn.workers.UvicornWorker --preload --timeout 120"
        with open(f"{path}/run.sh", "w") as output:
            output.write(gunicorn)
