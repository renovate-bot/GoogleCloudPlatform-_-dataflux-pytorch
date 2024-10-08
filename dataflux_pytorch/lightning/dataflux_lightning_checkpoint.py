"""
 Copyright 2024 Google LLC

 Licensed under the Apache License, Version 2.0 (the "License");
 you may not use this file except in compliance with the License.
 You may obtain a copy of the License at

      https://www.apache.org/licenses/LICENSE-2.0

 Unless required by applicable law or agreed to in writing, software
 distributed under the License is distributed on an "AS IS" BASIS,
 WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 See the License for the specific language governing permissions and
 limitations under the License.
 """
import io
from pathlib import Path
from typing import Any, Dict, Optional, Union

import torch
from dataflux_core import user_agent
from google.cloud import storage
from lightning.pytorch.plugins.io import AsyncCheckpointIO, CheckpointIO
from typing_extensions import override

from dataflux_pytorch.lightning.path_utils import parse_gcs_path
from dataflux_pytorch.multipart_upload.multipart import \
    upload_chunks_concurrently_from_bytesio as upload


class DatafluxLightningCheckpoint(CheckpointIO):
    """A checkpoint manager for GCS using the :class:'CheckpointIO' interface"""

    def __init__(
        self,
        project_name: str,
        storage_client: Optional[storage.Client] = None,
        disable_multipart: bool = False,
    ):
        self.project_name = project_name
        self.storage_client = storage_client
        self.disable_multipart = disable_multipart
        if not storage_client:
            self.storage_client = storage.Client(project=self.project_name, )
        user_agent.add_dataflux_user_agent(self.storage_client)

    def save_checkpoint(
        self,
        checkpoint: Dict[str, Any],
        path: Union[str, Path],
        storage_options: Optional[Any] = None,
    ) -> None:
        bucket_name, key = parse_gcs_path(path)
        bucket_client = self.storage_client.bucket(bucket_name)
        blob = bucket_client.blob(key)
        if self.disable_multipart:
            with blob.open("wb", ignore_flush=True) as blobwriter:
                torch.save(checkpoint, blobwriter)
        else:
            fb = io.BytesIO()
            torch.save(checkpoint, fb)
            upload(fb, blob)

    def load_checkpoint(
        self,
        path: Union[str, Path],
        map_location: Optional[Any] = None,
    ) -> Dict[str, Any]:
        bucket_name, key = parse_gcs_path(path)
        bucket_client = self.storage_client.bucket(bucket_name)
        blob = bucket_client.blob(key)
        stream = io.BytesIO()
        blob.download_to_file(stream)
        stream.seek(0)
        return torch.load(stream, map_location)

    def remove_checkpoint(
        self,
        path: Union[str, Path],
    ) -> None:
        bucket_name, key = parse_gcs_path(path)
        bucket_client = self.storage_client.bucket(bucket_name)
        blob = bucket_client.blob(key)
        blob.delete()

    def teardown(self, ) -> None:
        pass


class DatafluxLightningAsyncCheckpoint(AsyncCheckpointIO):
    """A checkpoint manager for GCS using the :class:'AsyncCheckpointIO' interface"""

    def __init__(
        self,
        project_name: str,
        storage_client: Optional[storage.Client] = None,
        disable_multipart: bool = False,
    ):
        super().__init__(
            DatafluxLightningCheckpoint(project_name,
                                        storage_client=storage_client,
                                        disable_multipart=disable_multipart))

    @override
    def teardown(self) -> None:
        # Ensure the DatafluxLightningCheckpoint teardown method gets called
        # in addition to the AsyncCheckpointIO teardown method.
        if getattr(super(), 'checkpoint_io', None) is not None:
            super().checkpoint_io.teardown()
        super().teardown()
