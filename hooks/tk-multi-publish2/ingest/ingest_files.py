# Copyright (c) 2017 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.


import traceback
import pprint

import sgtk


HookBaseClass = sgtk.get_hook_baseclass()

UNLINKED_ENTITY_TYPE = "(UNLINKED)"


class IngestFilesPlugin(HookBaseClass):
    """
    Inherits from PublishFilesPlugin
    """

    @property
    def settings_schema(self):
        """
        Dictionary defining the settings that this plugin expects to receive
        through the settings parameter in the accept, validate, publish and
        finalize methods.

        A dictionary on the following form::

            {
                "Settings Name": {
                    "type": "settings_type",
                    "default_value": "default_value",
                    "description": "One line description of the setting"
            }

        The type string should be one of the data types that toolkit accepts
        as part of its environment configuration.
        """
        schema = super(IngestFilesPlugin, self).settings_schema

        ingest_schema = {
            "additional_publish_fields": {
                "default_value": {"name": "sg_element", "output": "sg_output",
                                  "tags": "tags", "sg_snapshot_id": "sg_snapshot_id",
                                  "snapshot_type": "sg_snapshot_type"}
            },
            "snapshot_type_settings": {
                # custom entities can still be enabled.
                # "default_value": {"work_plate": "Element", "match_qt": "Element", "*": "Asset", "ingest": "Element"}
                "default_value": {"*": UNLINKED_ENTITY_TYPE}
            }
        }

        # add tags also to publish files
        schema["Item Type Settings"]["values"]["items"].update(ingest_schema)

        return schema

    @property
    def description(self):
        """
        Verbose, multi-line description of what the plugin does. This can
        contain simple html for formatting.
        """

        loader_url = "https://support.shotgunsoftware.com/hc/en-us/articles/219033078"

        return """
        <p>Ingests the file to the location specified by the publish_path_template
        for this item and creates a <b>PublishedFile</b> entity in Shotgun, 
        which will include a reference to the file's published path on disk.</br>
        
        <h3>Ingestion Process</h3>
        After the <b>PublishedFile</b> is created successfully, 
        a <b>Plate/Asset</b> entity is also created.The <b>PublishedFile</b> is 
        then linked to it's corresponding <b>Plate/Asset</b> entity for the users.
        After ingestion these files can be accessed via the 
        <b><a href='%s'>Loader</a></b></p>
        """ % (loader_url,)

    def accept(self, task_settings, item):
        """
        Method called by the publisher to determine if an item is of any
        interest to this plugin. Only items matching the filters defined via the
        item_filters property will be presented to this method.

        A publish task will be generated for each item accepted here. Returns a
        dictionary with the following booleans:

            - accepted: Indicates if the plugin is interested in this value at
                all. Required.
            - enabled: If True, the plugin will be enabled in the UI, otherwise
                it will be disabled. Optional, True by default.
            - visible: If True, the plugin will be visible in the UI, otherwise
                it will be hidden. Optional, True by default.
            - checked: If True, the plugin will be checked in the UI, otherwise
                it will be unchecked. Optional, True by default.

        :param item: Item to process

        :returns: dictionary with boolean keys accepted, required and enabled
        """

        accept_data = super(IngestFilesPlugin, self).accept(task_settings, item)

        return accept_data

    def validate(self, task_settings, item):
        """
        Validates the given item to check that it is ok to publish.

        Returns a boolean to indicate validity.

        :param task_settings: Dictionary of settings
        :param item: Item to process

        :returns: True if item is valid, False otherwise.
        """

        # this has to run first so that item properties are populated.
        # This also makes sure we are running within a valid context.
        # Properties are used to find a linked entity.
        status = super(IngestFilesPlugin, self).validate(task_settings, item)

        # ---- this check will only run if the status of the published files is true.
        # ---- check for matching linked_entity of this path with a status.
        # ---- In case of unlinked entity, this validation doesn't run.
        linked_entity_fields = ["sg_status_list"]
        linked_entity = self._find_linked_entity(task_settings, item, linked_entity_fields)
        if status and item.properties["linked_entity_type"] != UNLINKED_ENTITY_TYPE:
            if linked_entity:
                conflict_info = (
                    "This matching %s Entity will be updated and also linked to a new PublishedFile"
                    "<pre>%s</pre>" % (item.properties["linked_entity_type"], pprint.pformat(linked_entity),)
                )
                self.logger.info(
                    "Found a matching %s in Shotgun for item %s" % (item.properties["linked_entity_type"], item.name),
                    extra={
                        "action_show_more_info": {
                            "label": "Show %s" % item.properties["linked_entity_type"],
                            "tooltip": "Show the matching linked_entity in Shotgun",
                            "text": conflict_info
                        }
                    }
                )

            else:
                if item.properties["linked_entity_type"] == "Asset":
                    asset_type_status = self._create_asset_type(task_settings, item)
                    if asset_type_status:
                        self.logger.info("Created %s asset type!" % item.properties["fields"]["snapshot_type"])

                    if asset_type_status is None:
                        # failed to create the asset_type abort!
                        return False

                    self.logger.info("%s entity will be created of type %s for item %s"
                                     % (item.properties["linked_entity_type"],
                                        item.properties["fields"]["snapshot_type"],
                                        item.name))
                else:
                    self.logger.info("%s entity will be created for item %s"
                                     % (item.properties["linked_entity_type"], item.name))

        elif status:
            self.logger.info("Published Files will be created %s for item %s"
                             % (item.properties["linked_entity_type"], item.name))

        return status

    def create_published_files(self, task_settings, item):
        """
        Publishes the files for the given item and task_settings.
        This can call super or implement it's own.

        :param task_settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the task_settings property. The values are `Setting`
            instances.
        :param item: Item to process
        """

        # publish the file
        super(IngestFilesPlugin, self).publish(task_settings, item)

    def publish(self, task_settings, item):
        """
        Executes the publish logic for the given item and task_settings.

        :param task_settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the task_settings property. The values are `Setting`
            instances.
        :param item: Item to process
        """

        # create a linked_entity entity after the publish has gone through successfully.
        linked_entity = self._create_linked_entity(task_settings, item)

        # let's create ingest_entity_data within item properties,
        # so that we can link the version created to linked entity as well.
        if linked_entity:
            item.properties["ingest_entity_data"] = linked_entity

        if "ingest_entity_data" in item.properties:
            # run the actual publish file creation
            self.create_published_files(task_settings, item)

            if item.properties.get("sg_publish_data_list"):
                # link the publish file to our linked entity.
                updated_linked_entity = self._link_published_files_to_entity(task_settings, item)

                if updated_linked_entity:
                    # clear the status list of the linked_entity
                    self._clear_linked_entity_status_list(task_settings, item)
                    self.logger.info("%s entity registered and PublishedFile linked for %s" %
                                     (item.properties["linked_entity_type"], item.name))
                else:
                    # undo the linked_entity creation
                    self.undo(task_settings, item)
                    # undo the parent publish
                    super(IngestFilesPlugin, self).undo(task_settings, item)
                    self.logger.error("Failed to link the PublishedFile and the %s entity for %s!" %
                                      (item.properties["linked_entity_type"], item.name))
            else:
                # undo the linked_entity creation
                self.undo(task_settings, item)
                self.logger.error("PublishedFile not created successfully for %s!" % item.name)
        # configured to not create any custom linking.
        elif item.properties["linked_entity_type"] == UNLINKED_ENTITY_TYPE:
            # run the actual publish file creation
            self.create_published_files(task_settings, item)

            if not item.properties.get("sg_publish_data_list"):
                # undo the linked_entity creation
                self.undo(task_settings, item)
                self.logger.error("PublishedFile not created successfully for %s!" % item.name)
        else:
            self.logger.error("Failed to create a %s entity for %s!" %
                              (item.properties["linked_entity_type"], item.name))

    def finalize(self, task_settings, item):
        """
        Execute the finalization pass. This pass executes once
        all the publish tasks have completed, and can for example
        be used to version up files.

        :param task_settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the task_settings property. The values are `Setting`
            instances.
        :param item: Item to process
        """

        super(IngestFilesPlugin, self).finalize(task_settings, item)

        if "ingest_entity_data" in item.properties:
            # get the data for the linked_entity that was just created in SG
            linked_entity_data = item.properties["ingest_entity_data"]

            path = item.properties["path"]

            self.logger.info(
                "%s created for file: %s" % (item.properties["linked_entity_type"], path),
                extra={
                    "action_show_in_shotgun": {
                        "label": "Show %s" % item.properties["linked_entity_type"],
                        "tooltip": "Open the Publish in Shotgun.",
                        "entity": linked_entity_data
                    }
                }
            )

    def undo(self, task_settings, item):
        """
        Execute the undo method. This method will
        delete the linked_entity entity that got created due to the publish.

        :param task_settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the task_settings property. The values are `Setting`
            instances.
        :param item: Item to process
        """

        if "ingest_entity_data" in item.properties:
            linked_entity_data = item.properties["ingest_entity_data"]

            linked_entity_fields = ["sg_published_files"]
            linked_entity = self._find_linked_entity(task_settings, item, linked_entity_fields)

            # only delete the entity if the entity has no published files linked to it.
            if linked_entity_data and linked_entity and len(linked_entity["sg_published_files"]) == 0:
                try:
                    self.sgtk.shotgun.delete(linked_entity_data["type"], linked_entity_data["id"])
                    # pop the ingest_entity_data too!
                    item.properties.pop("ingest_entity_data")
                except Exception:
                    self.logger.error(
                        "Failed to delete %s Entity for %s" % (item.properties["linked_entity_type"], item.name),
                        extra={
                            "action_show_more_info": {
                                "label": "Show Error Log",
                                "tooltip": "Show the error log",
                                "text": traceback.format_exc()
                            }
                        }
                    )

    def _create_asset_type(self, task_settings, item):
        """Updates the sg_asset_type schema on SG to add the snapshot_type, if it doesn't already exist.

        :param item: Item to get the snapshot_type from
        :param task_settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the task_settings property. The values are `Setting`
            instances.
        :return: Status if the sg_asset_type schema got successfully updated or not.
        """

        if item.properties["linked_entity_type"] == "Asset":
            sg_asset_type_schema = self.sgtk.shotgun.schema_field_read("Asset", "sg_asset_type")
            existing_asset_types = sg_asset_type_schema["sg_asset_type"]["properties"]["valid_values"]["value"]
            item_fields = item.properties["fields"]

            snapshot_type = item_fields["snapshot_type"]

            if snapshot_type not in existing_asset_types:
                existing_asset_types.append(snapshot_type)
                try:
                    # update the schema for sg_asset_type
                    return self.sgtk.shotgun.schema_field_update("Asset", "sg_asset_type",
                                                                 {"valid_values": existing_asset_types})
                except Exception as e:
                    self.logger.error(
                        "failed to updated sg_asset_type schema for item: %s" % item.name,
                        extra={
                            "action_show_more_info": {
                                "label": "Show Error Log",
                                "tooltip": "Show the error log",
                                "text": traceback.format_exc()
                            }
                        }
                    )
                    return None
            else:
                return False


    def _resolve_linked_entity_type(self, task_settings, item):
        """
        Resolve the entity that needs to be created for the item.

        :param task_settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the task_settings property. The values are `Setting`
            instances.
        :param item: Item to get the snapshot_type from
        :return: If a mapped snapshot_type is found in the snapshot_type_settings it returns that entity type
        else it returns the value against "*" in snapshot_type_settings.
        snapshot_type should always be defined in item fields, for this to work.
        """

        snapshot_settings = task_settings['snapshot_type_settings'].value

        item_fields = item.properties["fields"]

        if "snapshot_type" not in item_fields:
            raise Exception("snapshot_type not found in item fields!\n %s" % pprint.pformat(item_fields))

        if item_fields["snapshot_type"] in snapshot_settings:
            return snapshot_settings[item_fields["snapshot_type"]]
        else:
            return snapshot_settings["*"]

    def _clear_linked_entity_status_list(self, task_settings, item):
        """
        Sets the status list on the linked_entity to None.
        Once the linked_entity has been completely linked to it's PublishedFile entity.

        :param task_settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the task_settings property. The values are `Setting`
            instances.
        :param item:  item to get the linked entity from
        """
        if "ingest_entity_data" in item.properties:
            try:
                self.sgtk.shotgun.update(
                    entity_type=item.properties["ingest_entity_data"]["type"],
                    entity_id=item.properties["ingest_entity_data"]["id"],
                    data={"sg_status_list": None},
                )
            except Exception:
                self.logger.error(
                    "clear_linked_entity_status_list failed for item: %s" % item.name,
                    extra={
                        "action_show_more_info": {
                            "label": "Show Error Log",
                            "tooltip": "Show the error log",
                            "text": traceback.format_exc()
                        }
                    }
                )

    def _find_linked_entity(self, task_settings, item, fields=list()):
        """
        Finds a linked entity corresponding to the item's context.
        Name of the New Entity is governed by "publish_linked_entity_name" of the item.
        Further filters it down if the context is from shot/sequence.

        :param task_settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the task_settings property. The values are `Setting`
            instances.
        :param item: item to find the linked entity for.
        :return: linked entity or None if not found.
        """

        # add the linked_entity_type to item properties
        item.properties["linked_entity_type"] = self._resolve_linked_entity_type(task_settings, item)

        if item.properties["linked_entity_type"] == UNLINKED_ENTITY_TYPE:
            # we don't create any entity in this case.
            return

        sg_filters = [
            ['project', 'is', item.context.project],
            ['code', 'is', item.properties["publish_linked_entity_name"]]
        ]

        if item.context.entity:
            if item.context.entity["type"] == "Shot":
                sg_filters.append(['sg_shot', 'is', item.context.entity])
            elif item.context.entity["type"] == "Sequence":
                sg_filters.append(['sg_sequence', 'is', item.context.entity])
            elif item.context.entity["type"] == "Asset":
                if item.properties["linked_entity_type"] == "Asset":
                    sg_filters.append(['parents', 'is', item.context.entity])
                if item.properties["linked_entity_type"] == "Element":
                    sg_filters.append(['assets', 'in', item.context.entity])

        fields.extend(['shots', 'code', 'id'])

        item_fields = item.properties["fields"]

        snapshot_type = item_fields["snapshot_type"]

        if item.properties["linked_entity_type"] == "Asset":
            sg_filters.append(['sg_asset_type', 'is', snapshot_type])

        result = self.sgtk.shotgun.find_one(
            entity_type=item.properties["linked_entity_type"],
            filters=sg_filters,
            fields=fields
        )
        return result

    def _get_frame_range(self, item):
        """
        Frame range for the item.

        :param item: item to get the frame range for.
        :return: A tuple of first_frame, last_frame
        """
        publisher = self.parent

        # Determine if this is a sequence of paths
        if item.properties["is_sequence"]:
            first_frame = publisher.util.get_frame_number(item.properties["sequence_paths"][0])
            last_frame = publisher.util.get_frame_number(item.properties["sequence_paths"][-1])
        else:
            first_frame = last_frame = 0

        return first_frame, last_frame

    def _create_linked_entity(self, task_settings, item):
        """
        Creates a linked entity if it doesn't exist for a given item, or updates it if it already exists.
        Sets the status of the linked entity to "ip"

        :param task_settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the task_settings property. The values are `Setting`
            instances.
        :param item: item to create the linked entity for.
        :return: Linked entity for the given item.
        """

        # don't create any entity when it's unlinked
        if item.properties["linked_entity_type"] == UNLINKED_ENTITY_TYPE:
            return

        try:
            linked_entity = self._find_linked_entity(task_settings, item)
        except Exception as e:
            self.logger.error(
                "create_linked_entity failed for item: %s" % item.name,
                extra={
                    "action_show_more_info": {
                        "label": "Show Error Log",
                        "tooltip": "Show the error log",
                        "text": traceback.format_exc()
                    }
                }
            )
            raise e

        data = dict(
            code=item.properties["publish_linked_entity_name"],
            # TODO-- disabling this since this makes more sense on PublishedFile Now!
            # sg_client_name=item.name,
            sg_status_list="ip"
        )

        item_fields = item.properties["fields"]

        snapshot_type = item_fields["snapshot_type"]

        if item.properties["linked_entity_type"] == "Asset":
            data["sg_asset_type"] = snapshot_type

        # all this is being handled by Version entity for the file types that need frame ranges!
        # frange = self._get_frame_range(item)
        # data["head_in"] = frange[0]
        # data["head_out"] = frange[1]

        if item.context.entity:
            # link the new entity to a Sequence and Shot
            if item.context.entity["type"] == "Shot":
                data["sg_shot"] = item.context.entity
                # search the corresponding sequence entity in additional entities
                sequence_entity = [entity for entity in item.context.additional_entities
                                   if entity["type"] == "Sequence"]
                if sequence_entity:
                    data["sg_sequence"] = sequence_entity[0]
            # link the new entity to a Sequence
            elif item.context.entity["type"] == "Sequence":
                data["sg_sequence"] = item.context.entity
            # link the new entity to an Asset
            elif item.context.entity["type"] == "Asset" and item.properties["linked_entity_type"] == "Asset":
                if item.properties["linked_entity_type"] == "Asset":
                    # add the context asset entity as the parent asset
                    data["parents"] = [item.context.entity]
                if item.properties["linked_entity_type"] == "Element":
                    # add the context asset entity as a plate
                    data["elements"] = [item.context.entity]


                # if it's a sequence based asset
                sequence_entity = [entity for entity in item.context.additional_entities
                                   if entity["type"] == "Sequence"]
                if sequence_entity:
                    data["sg_sequence"] = sequence_entity[0]

                # if it's a shot based asset
                shot_entity = [entity for entity in item.context.additional_entities if entity["type"] == "Shot"]
                if shot_entity:
                    data["sg_shot"] = shot_entity[0]

        try:
            if linked_entity:
                linked_entity = self.sgtk.shotgun.update(
                    entity_type=item.properties["linked_entity_type"],
                    entity_id=linked_entity['id'],
                    data=data,
                    multi_entity_update_modes=dict(shots='add', parents='add'),
                )
                self.logger.info(
                    "Updated %s entity..." % item.properties["linked_entity_type"],
                    extra={
                        "action_show_more_info": {
                            "label": "%s Data" % item.properties["linked_entity_type"],
                            "tooltip": "Show the complete %s data dictionary" % item.properties["linked_entity_type"],
                            "text": "<pre>%s</pre>" % (pprint.pformat(data),)
                        }
                    }
                )
            else:

                data["project"] = item.context.project
                linked_entity = self.sgtk.shotgun.create(
                    entity_type=item.properties["linked_entity_type"],
                    data=data
                )
                self.logger.info(
                    "Created %s entity..." % item.properties["linked_entity_type"],
                    extra={
                        "action_show_more_info": {
                            "label": "%s Data" % item.properties["linked_entity_type"],
                            "tooltip": "Show the complete %s data dictionary" % item.properties["linked_entity_type"],
                            "text": "<pre>%s</pre>" % (pprint.pformat(data),)
                        }
                    }
                )

            return linked_entity
        except Exception as e:
            self.logger.error(
                "create_linked_entity failed for item: %s" % item.name,
                extra={
                    "action_show_more_info": {
                        "label": "Show Error Log",
                        "tooltip": "Show the error log",
                        "text": traceback.format_exc()
                    }
                }
            )
            raise e

    def _link_published_files_to_entity(self, task_settings, item):
        """
        Link the new entity to its corresponding publish files.

        :param task_settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the task_settings property. The values are `Setting`
            instances.
        :param item: item to get the publish files(sg_publish_data_list) and linked entity(ingest_entity_data)
        :return: Updated linked entity.
        """

        if "ingest_entity_data" not in item.properties:
            return

        sg_publish_data_list = []

        if "sg_publish_data_list" in item.properties:
            sg_publish_data_list.extend(item.properties.sg_publish_data_list)

        try:
            result = self.sgtk.shotgun.update(
                entity_type=item.properties["ingest_entity_data"]["type"],
                entity_id=item.properties["ingest_entity_data"]["id"],
                data=dict(sg_published_files=sg_publish_data_list),
                multi_entity_update_modes=dict(sg_published_files='add'),
            )
            return result
        except Exception:
            self.logger.error(
                "link_published_files_to_entity failed for item: %s" % item.name,
                extra={
                    "action_show_more_info": {
                        "label": "Show Error Log",
                        "tooltip": "Show the error log",
                        "text": traceback.format_exc()
                    }
                }
            )
            return

    def _get_publish_version(self, task_settings, item):
        """
        Get the publish version for the supplied item.

        :param item: The item to determine the publish version for

        Extracts the publish version from the item's "version" field
        """

        # TODO: push this method back to basic/publish.py
        # The get the version number from the path, if defined
        return int(item.properties.fields.get("version", 1))
