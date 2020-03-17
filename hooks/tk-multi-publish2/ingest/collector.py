# Copyright (c) 2017 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.

import os
import datetime
import traceback
import pprint
import re
import urllib

from functools import reduce
import operator

import sgtk
import tank
from tank_vendor import yaml

HookBaseClass = sgtk.get_hook_baseclass()

# This is a dictionary of fields in snapshot from manifest and it's corresponding field on the item.
DEFAULT_MANIFEST_SG_MAPPINGS = {
    "file": {
        "snapshots": {
            "id": "sg_snapshot_id",
            "user": "snapshot_user",
            "name": "manifest_name",
            "version": "snapshot_version",
        },
    },
    "note": {
        "notes": {
            "notes": "description",
            "name": "snapshot_name",
            "body": "content",
            "id": "sg_client_note_id",
        },
        "snapshots": {
            "id": "sg_snapshot_id",
            "user": "snapshot_user",
            "name": "manifest_name",
            "version": "snapshot_version",
        },
        "versions": {
            "id": "sg_client_version_id",
            "name": "version_name",
        },
    },
}

# This is a dictionary of note_type values to item type.
DEFAULT_NOTE_TYPES_MAPPINGS = {
    "kickoff": "kickoff",
    "role supervisor": "annotation",
    "dailies": "annotation",
}

# Default snapshot_type
DEFAULT_SNAPSHOT_TYPE = "ingest"

# This is a dictionary of note_type values to their access keys in the fields dict.
DEFAULT_NOTE_TYPES_ACCESS_FALLBACKS = {
    "kickoff": [["sg_version", "original_name"], ["sg_version", "name"],
                ["ingest_note_links", "Version", "original_name"],
                ["ingest_note_links", "Version", "name"]],
    "annotation": [["sg_version", "original_name"], ["sg_version", "name"],
                   ["ingest_note_links", "Version", "original_name"],
                   ["ingest_note_links", "Version", "name"]]
}


class IngestCollectorPlugin(HookBaseClass):
    """
    Collector that operates on the current set of ingestion files. Should
    inherit from the basic collector hook.

    This instance of the hook uses default_fields, default_snapshot_type from item settings.

    """

    @property
    def settings_schema(self):
        """
        Dictionary defining the settings that this collector expects to receive
        through the settings parameter in the process_current_session and
        process_file methods.

        A dictionary on the following form::

            {
                "Settings Name": {
                    "type": "settings_type",
                    "default_value": "default_value",
                    "description": "One line description of the setting"
            }

        The type string should be one of the data types that toolkit accepts as
        part of its environment configuration.
        """
        schema = super(IngestCollectorPlugin, self).settings_schema
        items_schema = schema["Item Types"]["values"]["items"]
        items_schema["default_snapshot_type"] = {
            "type": "str",
            "description": "Specifies the default snapshot type to be used for an ingested item.",
            "allows_empty": True,
            "default_value": DEFAULT_SNAPSHOT_TYPE,
        }
        items_schema["default_fields"] = {
            "type": dict,
            "values": {
                "type": "str",
            },
            "allows_empty": True,
            "default_value": {},
            "description": "Default fields to use, with this item"
        }
        items_schema["manifest_field_filters"] = {
            "type": dict,
            "values": {
                "type": "str",
            },
            "allows_empty": True,
            "default_value": {},
            "description": (
                    "This imposes one restriction, "
                    "that only item types which have matching work_path_template are valid candidates."
                    "Dictionary of Key in manifest_file_fields"
                    "'%<operator method>:expected_value:expected_result%' will get the method from operator module"
                    "'#<value operator method>:expected_value:expected_result#' will get method from value of the key"
                    "if all the conditions are matching, the match score will be subtracted from the "
                    "highest resolution order,  else the item will be pushed to the last priority to maintain"
                    "backwards compatibility with the initial behaviour."
            )
        }
        schema["Manifest SG Mappings"] = {
            "type": "dict",
            "values": {
                "type": "dict",
                "values": {
                    "type": "dict",
                    "values": {
                        "type": "str",
                    },
                },
            },
            "default_value": DEFAULT_MANIFEST_SG_MAPPINGS,
            "allows_empty": True,
            "description": "Mapping of keys in Manifest to SG template keys."
        }
        schema["Note Type Mappings"] = {
            "type": "dict",
            "values": {
                "type": "str",
            },
            "default_value": DEFAULT_NOTE_TYPES_MAPPINGS,
            "allows_empty": True,
            "description": "dictionary of note_type values to their item type."
        }
        schema["Note Type Access Fallbacks"] = {
            "type": "dict",
            "values": {
                "type": "list",
                "values": {
                    "type": "list",
                    "values": {
                        "type": "str",
                    },
                },
            },
            "default_value": DEFAULT_NOTE_TYPES_ACCESS_FALLBACKS,
            "allows_empty": True,
            "description": "Dictionary of note_type values to a list of access keys in the fields dict."
        }
        schema["Ignore Extensions"] = {
            "type": "list",
            "values": {
                "type": "str"
            },
            "allows_empty": True,
            "default_value": [],
            "description": "List of extensions to be ignored by the collector."
        }
        schema["Ignore Filename"] = {
            "type": "list",
            "values": {
                "type": "str"
            },
            "allows_empty": True,
            "default_value": [],
            "description": "List of strings to ignore a filename by the collector."
        }
        schema["Manifest File Name"] = {
            "type": "str",
            "allows_empty": True,
            "default_value": "contents.yaml",
            "description": "Name of the file to look for, as a source for processing files to be ingested."
        }
        schema["Properties To Display"] = {
            "type": "list",
            "values": {
                "type": "dict"
            },
            "default_value": [
                {
                    "name": "fields",
                    "display_name": "Item Fields",
                    "editable": True,
                    "editable_fields": ["^((?!SEQ|eye|MM|DD|YYYY).)*$"],
                    "type": "FieldsPropertyWidget"
                },
                {
                    "name": "missing_fields",
                    "creation_property": "fields",
                    "display_name": "Missing Fields",
                    "editable": True,
                    "editable_fields": ["^.*$"],
                    "type": "FieldsCreatePropertyWidget"
                },
                {
                    "name": "context_fields",
                    "display_name": "Context Fields",
                    "type": "FieldsPropertyWidget"
                },
            ],
            "allows_empty": True,
            "description": (
                "A list of properties to display in the UI. Each entry in the list is a dict "
                "that defines the associated property name, the widget class to use, as well "
                "as any keyword arguments to pass to the constructor."
            ),
        }
        return schema

    class FieldsCreatePropertyWidget(HookBaseClass.FieldsPropertyWidget):
        def __init__(self, parent, hook, items, name, **kwargs):

            # apply_changes will commit the field changes on creation_property
            # by default it commits changes to property changes on self._name
            self._creation_property = kwargs.pop("creation_property", name)

            super(IngestCollectorPlugin.FieldsCreatePropertyWidget, self).__init__(
                parent, hook, items, name, **kwargs)

        def apply_changes(self):
            """Store persistent data on the properties object"""
            for item in self._items:
                for key, value in self._fields.iteritems():
                    if value == self.MultiplesValue or \
                            not any([re.match(pattern, key) for pattern in self._editable_fields]):
                        # Don't override value with multiples key,
                        # or even keys that are not editable.
                        continue
                    # update the item.properties.fields
                    item.properties[self._name][key] = value
                    item.properties[self._creation_property][key] = value

    def _resolve_work_path_template(self, settings, item):
        """
        Resolve work_path_template from the collector settings for the specified item.

        :param dict settings: Configured settings for this collector
        :param item: The Item instance
        :return: Name of the template.
        """
        path = item.properties.get("path")
        if not path:
            return None

        # try using the basename for resolving the template
        work_path_template = self._get_work_path_template_from_settings(settings,
                                                                         item.type,
                                                                         os.path.basename(path))
        if work_path_template:
            return work_path_template

        return super(IngestCollectorPlugin, self)._resolve_work_path_template(settings, item)

    def _add_file_item(self, settings, parent_item, path, is_sequence=False, seq_files=None,
                    item_name=None, item_type=None, context=None, creation_properties=None):
        """
        Creates a file item

        :param dict settings: Configured settings for this collector
        :param parent_item: parent item instance
        :param path: Path to analyze
        :param is_sequence: Bool as to whether to treat the path as a part of a sequence
        :param seq_files: A list of files in the sequence
        :param item_name: The name of the item instance
        :param item_type: The type of the item instance
        :param context: The :class:`sgtk.Context` to set for the item
        :param creation_properties: The dict of initial properties for the item

        :returns: The item that was created
        """

        publisher = self.parent

        if settings["Ignore Extensions"].value or settings["Ignore Filename"].value:
            ignored_extensions = settings["Ignore Extensions"].value
            ignored_filename = settings["Ignore Filename"].value

            file_components = publisher.util.get_file_path_components(path)
            extension_ignored = False
            filename_ignored = False

            if file_components["extension"] in ignored_extensions:
                extension_ignored = True

            if ignored_filename:
                filename_ignored = any(re.match(ignored_string, file_components["filename"])
                                       for ignored_string in ignored_filename)

            if extension_ignored or filename_ignored:

                if is_sequence:
                    # include an indicator that this is an image sequence and the known
                    # file that belongs to this sequence
                    ignore_warning = (
                        "The following files were ignored:<br>"
                        "<pre>%s</pre>" % (pprint.pformat(seq_files),)
                    )
                else:
                    ignore_warning = (
                        "The following file was ignored:<br>"
                        "<pre>%s</pre>" % (path,)
                    )

                self.logger.warning(
                    "Ignoring the file: %s" % file_components["filename"],
                    extra={
                        "action_show_more_info": {
                            "label": "Show File(s)",
                            "tooltip": "Show the ignored file",
                            "text": ignore_warning
                        }
                    }
                )
                return

        item = super(IngestCollectorPlugin, self)._add_file_item(settings, parent_item, path, is_sequence, seq_files,
                                                                 item_name, item_type, context, creation_properties)

        # create/add the properties required for missing fields and context fields
        if "missing_fields" not in item.properties:
            item.properties.missing_fields = dict()

        if "context_fields" not in item.properties:
            item.properties.context_fields = dict()

        return item

    def _add_note_item(self, settings, parent_item, fields, is_sequence=False, seq_files=None):
        """
        Process the supplied list of attachments, and create a note item.

        :param dict settings: Configured settings for this collector
        :param parent_item: parent item instance
        :param fields: Fields from manifest

        :returns: The item that was created
        """

        publisher = self.parent

        note_type_mappings = settings["Note Type Mappings"].value
        note_type_acess_fallbacks = settings["Note Type Access Fallbacks"].value

        raw_item_settings = settings["Item Types"].raw_value

        manifest_note_type = fields["note_type"]

        if manifest_note_type not in note_type_mappings:
            self.logger.error(
                "Note type not recognized %s" % manifest_note_type,
                extra={
                    "action_show_more_info": {
                        "label": "Valid Types",
                        "tooltip": "Show Valid Note Types",
                        "text": "Valid Note Type Mappings: %s" % (pprint.pformat(note_type_mappings),)
                    }
                }
            )
            return

        note_type = note_type_mappings[manifest_note_type]

        work_path_template = None

        for note_type_acess_keys in note_type_acess_fallbacks[note_type]:
            try:
                path = reduce(operator.getitem, note_type_acess_keys, fields) + ".%s" % note_type
                display_name = path + ".notes"
            except Exception:
                self.logger.warning("Unable to resolve a path using keys.",
                                    extra={
                                        "action_show_more_info": {
                                            "label": "Show Keys",
                                            "tooltip": "Show the access keys used.",
                                            "text": "Keys: %s\nError: %s" % (note_type_acess_keys,
                                                                             traceback.format_exc())
                                        }
                                    })
                continue
            else:
                item_type = "notes.entity.%s" % note_type

                relevant_item_settings = raw_item_settings[item_type]
                raw_template_name = relevant_item_settings.get("work_path_template")
                envs = self.parent.sgtk.pipeline_configuration.get_environments()

                template_names_per_env = [
                    sgtk.platform.resolve_setting_expression(raw_template_name,
                                                             self.parent.engine.instance_name,
                                                             env_name) for env_name in envs
                ]

                templates_per_env = [self.parent.get_template_by_name(template_name) for template_name in
                                     template_names_per_env if self.parent.get_template_by_name(template_name)]
                for template in templates_per_env:
                    try:
                        template.get_fields(path)
                        # we have a match!
                        work_path_template = template.name
                    except:
                        # it errored out
                        continue

                if work_path_template:
                    # calculate the context and give to the item
                    context = self._get_item_context_from_path(work_path_template, path, parent_item)

                    file_item = self._add_file_item(settings, parent_item, path, item_name=display_name,
                                                    item_type=item_type, context=context)

                    # we found the template match in one of the fallbacks, break-out
                    return file_item
                else:
                    self.logger.warning("No matching template found for %s with raw template %s" % (path,
                                                                                                    raw_template_name),
                                        extra={
                                            "action_show_more_info": {
                                                "label": "Show Fields",
                                                "tooltip": "Show the fields used.",
                                                "text": note_type_acess_keys
                                            }
                                        })
                    continue

    def process_file(self, settings, parent_item, path):
        """
        Analyzes the given file and creates one or more items
        to represent it.

        :param dict settings: Configured settings for this collector
        :param parent_item: Root item instance
        :param path: Path to analyze

        :returns: The main item that was created, or None if no item was created
            for the supplied path
        """

        publisher = self.parent

        file_items = list()

        # handle Manifest files, Normal files and folders differently
        if os.path.isdir(path):
            items = self._collect_folder(settings, parent_item, path)
            if items:
                file_items.extend(items)
        else:
            if settings["Manifest File Name"].value in os.path.basename(path):
                items = self._collect_manifest_file(settings, parent_item, path)
                if items:
                    file_items.extend(items)
            else:
                item = self._collect_file(settings, parent_item, path)
                if item:
                    file_items.append(item)

        return file_items

    def _get_item_type_info(self, settings, item_type):
        """
        Return the dictionary corresponding to this item's 'Item Types' settings.

        :param dict settings: Configured settings for this collector
        :param item_type: The type of Item to identify info for

        :return: A dictionary of information about the item to create::

            # item_type = "file.image.sequence"

            {
                "extensions": ["jpeg", "jpg", "png"],
                "type_display": "Rendered Image Sequence",
                "icon_path": "/path/to/some/icons/folder/image_sequence.png",
                "work_path_template": "some_template_name"
            }
        """
        item_info = super(IngestCollectorPlugin, self)._get_item_type_info(settings, item_type)

        item_info.setdefault("default_snapshot_type", DEFAULT_SNAPSHOT_TYPE)
        item_info.setdefault("default_fields", dict())
        item_info.setdefault("manifest_field_filters", dict())

        # everything should now be populated, so return the dictionary
        return item_info

    def _resolve_item_fields(self, settings, item):
        """
        Populates the item's defaults that are to be stored on an ingested item.
        make sure we have snapshot_type field in the item!
        this is to make sure that on publish we retain this field to figure out asset creation is needed or not.

        :param dict settings: Configured settings for this collector
        :param item: Item to create/verify the defaults on
        """

        fields = super(IngestCollectorPlugin, self)._resolve_item_fields(settings, item)

        # make sure we don't pick a default name from the task, else everything will end up as "vendor"
        # this only happens in case of custom ingestion, since we let the user choose a vendor task
        # instead of automatically resolving to a "Vendor" Step.
        if item.context.task:
            name_field = item.context.task["name"]
            if fields["name"] == urllib.quote(name_field.replace(" ", "_").lower(), safe=''):
                fields.pop("name")

        item_info = self._get_item_type_info(settings, item.type)

        # restore the fields from the manifest file, even though we currently don't allow users to change context
        # when ingesting using the manifest file.
        if "manifest_file_fields" in item.properties:
            self.logger.info(
                "Re-creating manifest file fields for: %s" % item.name,
                extra={
                    "action_show_more_info": {
                        "label": "Show Info",
                        "tooltip": "Show more info",
                        "text": "Manifest fields:\n%s" %
                                (pprint.pformat(item.properties.manifest_file_fields))
                    }
                }
            )
            fields.update(item.properties.manifest_file_fields)

        if "snapshot_type" not in fields:
            fields["snapshot_type"] = item_info["default_snapshot_type"]
            # CDL files should always be published as Asset entity with nuke_avidgrade asset_type
            # this is to match organic, and also for Avid grade lookup on shotgun
            # this logic has been moved to _get_item_type_info by defining default_snapshot_type for each item type
            # if file_item.type == "file.cdl":
            #     fields["snapshot_type"] = "nuke_avidgrade"

            self.logger.info(
                "Injected snapshot_type field for item: %s" % item.name,
                extra={
                    "action_show_more_info": {
                        "label": "Show Info",
                        "tooltip": "Show more info",
                        "text": "Updated fields:\n%s" %
                                (pprint.pformat(fields))
                    }
                }
            )

        # create the defaults on the item, if we didn't already get them from the manifest.
        if "default_fields" in item_info:
            for key, value in item_info["default_fields"].iteritems():
                if key not in fields:
                    item_attr_match = re.match("%(.*)%", value)
                    # to assign value on item fields with attributes on the item object
                    if item_attr_match:
                        fields[key] = getattr(item, item_attr_match.groups()[0])
                    else:
                        fields[key] = value

        return fields

    def _process_manifest_file(self, settings, path):
        """
        Do the required processing on the yaml file, sanitisation or validations.
        conversions mentioned in Manifest Types setting of the collector hook.

        :param path: path to yaml file
        :return: list of processed snapshots, in the format
        [{file(type of collect method to run):
            {'fields': {'context_type': 'maya_model',
                        'department': 'model',
                        'description': 'n/a',
                        'instance_name': None,
                        'level': None,
                        'snapshot_name': 'egypt_riser_a',
                        'snapshot_type': 'maya_model',
                        'sg_snapshot_id': 1002060803L,
                        'subcontext': 'hi',
                        'type': 'asset',
                        'snapshot_user': 'rsariel',
                        'snapshot_version': 1},
             'files': {'/dd/home/gverma/work/SHARED/MODEL/enviro/egypt_riser_a/hi/maya_model/egypt_riser_a_hi_tag_v001.xml': ['tag_xml'],
                       '/dd/home/gverma/work/SHARED/MODEL/enviro/egypt_riser_a/hi/maya_model/egypt_riser_a_hi_transform_v001.xml': ['transform_xml'],
                       '/dd/home/gverma/work/SHARED/MODEL/enviro/egypt_riser_a/hi/maya_model/egypt_riser_a_hi_v001.mb': ['main', 'mayaBinary']}
            }
        }]
        """

        processed_snapshots = list()
        manifest_mappings = settings["Manifest SG Mappings"].value

        # since we only process snapshots in this manifest.
        file_item_manifest_mappings = manifest_mappings["file"]["snapshots"]

        # this is a bit more special since it has three different sources being processed.
        # notes, snapshots, versions. Each can have overlapping fields.
        note_item_manifest_mappings = manifest_mappings["note"]
        # yaml file stays at the base of the package
        base_dir = os.path.dirname(path)

        snapshots = list()
        notes = list()
        versions = list()
        notes_index = 0

        with open(path, 'r') as f:
            try:
                contents = yaml.load(f)
                snapshots = contents["snapshots"]
                if "notes" in contents:
                    notes = contents["notes"]
                if "versions" in contents:
                    versions = contents["versions"]
            except Exception:
                self.logger.error(
                    "Failed to read the manifest file %s" % path,
                    extra={
                        "action_show_more_info": {
                            "label": "Show Error Log",
                            "tooltip": "Show the error log",
                            "text": traceback.format_exc()
                        }
                    }
                )
                return processed_snapshots

        for snapshot in snapshots:
            # first replace all the snapshot with the Manifest SG Mappings
            data = dict()
            data["fields"] = {file_item_manifest_mappings[k] if k in file_item_manifest_mappings else k: v
                              for k, v in snapshot.iteritems()}

            # let's process file_types now!
            data["files"] = dict()
            file_types = data["fields"].pop("file_types")
            for file_type, files in file_types.iteritems():
                if "frame_range" in files:
                    p_file = files["files"][0]["path"]
                    p_file = os.path.join(base_dir, p_file)
                    # let's pick the first file and let the collector run _collect_folder on this
                    # since this is already a file sequence
                    append_path = os.path.dirname(p_file)
                    # list of tag names
                    if append_path not in data["files"]:
                        data["files"][append_path] = list()
                    data["files"][append_path].append(file_type)
                # not a file sequence store the file names, to run _collect_file
                else:
                    p_files = files["files"]
                    for p_file in p_files:
                        append_path = os.path.join(base_dir, p_file["path"])

                        # list of tag names
                        if append_path not in data["files"]:
                            data["files"][append_path] = list()
                        data["files"][append_path].append(file_type)

            processed_snapshots.append({"file": data})

        for note in notes:
            # first replace all the snapshot with the Manifest SG Mappings

            data = dict()
            snapshot_data = dict()
            version_data = dict()

            note_manifest_mappings = note_item_manifest_mappings["notes"]
            data["fields"] = {note_manifest_mappings[k] if k in note_manifest_mappings else k: v
                              for k, v in note.iteritems()}

            # special case handling for note links, this is a list of entities
            # it will converted to a dict in ingest_note_links <link["type"]>: link
            # this is to facilitate easier access using nested keys of a dict
            if "note_links" in note:
                data["fields"]["ingest_note_links"] = dict()
                for note_link in note["note_links"]:
                    data["fields"]["ingest_note_links"][note_link["type"]] = note_link

            # every note item might not have a corresponding snapshot and version associated with it
            # in that case don't pick out the fields from snapshot and version
            # notes are for most cases self contained and leaking into snapshot, version shouldn't be required
            if notes_index >= len(snapshots) or notes_index >= len(versions):
                note_snapshot = dict()
                note_version = dict()
            else:
                note_snapshot = snapshots[notes_index]
                note_version = versions[notes_index]

            # pop the notes from version_data they are already stored
            if "notes" in note_version:
                note_version.pop("notes")

            version_manifest_mappings = note_item_manifest_mappings["versions"]
            version_data["fields"] = {version_manifest_mappings[k] if k in version_manifest_mappings else k: v
                                      for k, v in note_version.iteritems()}

            # update the item fields with version_data fields
            data["fields"].update(version_data["fields"])

            # snapshot fields get priority over version fields
            snapshot_manifest_mappings = note_item_manifest_mappings["snapshots"]
            snapshot_data["fields"] = {snapshot_manifest_mappings[k] if k in snapshot_manifest_mappings else k: v
                                       for k, v in note_snapshot.iteritems()}

            # pop the files from snapshot_data they are not useful
            if "file_types" in note_snapshot:
                snapshot_data["fields"].pop("file_types")

            # update the item fields with snapshot_data fields
            data["fields"].update(snapshot_data["fields"])

            # let's process the attachments now!
            data["files"] = dict()
            attachments = data["fields"].pop("attachments")

            if attachments:
                # add one path of attachment for template parsing
                append_path = os.path.join(base_dir, attachments[0]["path"])

                if append_path not in data["files"]:
                    data["files"][append_path] = list()

            # re-create the attachments field for later use by publish
            data["fields"]["attachments"] = list()

            for attachment in attachments:
                data["fields"]["attachments"].append(os.path.join(base_dir, attachment["path"]))

            processed_snapshots.append({"note": data})

            # move to the next snapshot
            notes_index += 1

        return processed_snapshots

    def _query_associated_tags(self, tags):
        """
        Queries/Creates tag entities given a list of tag names.

        :param tags: List of tag names.
        :return: List of created/existing tag entities.
        """

        tag_entities = list()

        fields = ["name", "id", "code", "type"]
        for tag_name in tags:
            tag_entity = self.sgtk.shotgun.find_one(entity_type="Tag", filters=[["name", "is", tag_name]], fields=fields)
            if tag_entity:
                tag_entities.append(tag_entity)
            else:
                try:
                    new_entity = self.sgtk.shotgun.create(entity_type="Tag", data=dict(name=tag_name))
                    tag_entities.append(new_entity)
                except Exception:
                    self.logger.error(
                        "Failed to create Tag: %s" % tag_name,
                        extra={
                            "action_show_more_info": {
                                "label": "Show Error log",
                                "tooltip": "Show the error log",
                                "text": traceback.format_exc()
                            }
                        }
                    )
        return tag_entities

    def _collect_manifest_file(self, settings, parent_item, path):
        """
        Process the supplied manifest file.

        :param dict settings: Configured settings for this collector
        :param parent_item: parent item instance
        :param path: Path to analyze

        :returns: The item that was created
        """

        # process the manifest file first, replace the fields to relevant names.
        # collect the tags a file has too.
        processed_entities = self._process_manifest_file(settings, path)

        file_items = list()

        for entity in processed_entities:
            for hook_type, item_data in entity.iteritems():
                files = item_data["files"]
                # notes can be ingested without attachments as well.
                if not files and hook_type == "note":
                    # fields and items setup
                    fields = item_data["fields"].copy()
                    new_items = list()
                    # create a note item
                    item = self._add_note_item(settings, parent_item, fields=fields)
                    if item:
                        if "snapshot_name" in fields:
                            item.description = fields["snapshot_name"]

                        new_items.append(item)

                    for new_item in new_items:
                        # create a new property that stores the fields contained in manifest file for this item.
                        new_item.properties.manifest_file_fields = fields

                        item_fields = new_item.properties["fields"]
                        item_fields.update(fields)

                        if not new_item.description:
                            # adding a default description to item
                            new_item.description = "Created by shotgun_ingest on %s" % str(datetime.date.today())

                        self.logger.info(
                            "Updated fields from snapshot for item: %s" % new_item.name,
                            extra={
                                "action_show_more_info": {
                                    "label": "Show Info",
                                    "tooltip": "Show more info",
                                    "text": "Updated fields:\n%s" %
                                            (pprint.pformat(new_item.properties["fields"]))
                                }
                            }
                        )

                        # we can't let the user change the context of the file being ingested using manifest files
                        new_item.context_change_allowed = False
                    # put the new items back in collector
                    file_items.extend(new_items)

                for p_file, tags in files.iteritems():
                    # fields and items setup
                    fields = item_data["fields"].copy()
                    new_items = list()

                    # file type entity
                    if hook_type == "file":
                        # we need to add tag entities to this field.
                        # let's query/create those first.
                        fields["tags"] = self._query_associated_tags(tags)
                        if os.path.isdir(p_file):
                            items = self._collect_folder(settings, parent_item, p_file,
                                                         creation_properties={'manifest_file_fields': fields})
                            if items:
                                new_items.extend(items)
                        else:
                            item = self._collect_file(settings, parent_item, p_file,
                                                      creation_properties={'manifest_file_fields': fields})
                            if item:
                                new_items.append(item)
                    # note type item
                    elif hook_type == "note":
                        # create a note item
                        item = self._add_note_item(settings, parent_item, fields=fields)
                        if item:
                            if "snapshot_name" in fields:
                                item.description = fields["snapshot_name"]

                            new_items.append(item)

                    # inject the new fields into the item
                    for new_item in new_items:
                        # create a new property that stores the fields contained in manifest file for this item.
                        new_item.properties.manifest_file_fields = fields

                        item_fields = new_item.properties["fields"]
                        item_fields.update(fields)

                        if not new_item.description:
                            # adding a default description to item
                            new_item.description = "Created by shotgun_ingest on %s" % str(datetime.date.today())

                        self.logger.info(
                            "Updated fields from snapshot for item: %s" % new_item.name,
                            extra={
                                "action_show_more_info": {
                                    "label": "Show Info",
                                    "tooltip": "Show more info",
                                    "text": "Updated fields:\n%s" %
                                            (pprint.pformat(new_item.properties["fields"]))
                                }
                            }
                        )

                        # we can't let the user change the context of the file being ingested using manifest files
                        new_item.context_change_allowed = False

                    # put the new items back in collector
                    file_items.extend(new_items)

        return file_items

    def _get_filtered_item_types_from_settings(self, settings, path, is_sequence, creation_properties):

        """
        Returns a list of tuples containing (resolution_order, work_path_template, item_type).
        This filtered list of item types can then be passed down to resolve the correct item_type.

        :param dict settings: Configured settings for this collector
        :param path: The file path to identify type info for
        :param is_sequence: Bool whether or not path is a sequence path
        :param creation_properties: The dict of initial properties for the item
        """

        template_item_type_mapping = super(IngestCollectorPlugin,
                                           self)._get_filtered_item_types_from_settings(settings, path,
                                                                                        is_sequence,
                                                                                        creation_properties)

        found_matching_manifest_filter = False
        filtered_template_item_type_mapping = list()
        max_resolution_order = max(
            [resolution_order for resolution_order, work_path_template, item_type in template_item_type_mapping])

        # contains the logic that further filters the items based on creation_properties
        # which in case of manifest file based ingestion would contain a list of manifest_file_fields
        if "manifest_file_fields" in creation_properties:
            manifest_file_fields = creation_properties["manifest_file_fields"]

            for resolution_order, work_path_template, item_type in template_item_type_mapping:
                type_info = self._get_item_type_info(settings, item_type)
                manifest_field_filters = type_info["manifest_field_filters"]

                if work_path_template and manifest_field_filters:
                    match_score = 0

                    for field, parser_value in manifest_field_filters.iteritems():
                        field_value = manifest_file_fields.get(field)

                        if field_value:
                            field_value_match = False
                            operator_method = "not found"
                            expected_value = "not found"
                            expected_result = "not found"
                            # operator module specific parsing, '%<operator method>:expected_value:expected_result%'
                            operator_module_match = re.match("%(.*):(.*):(.*)%", parser_value)
                            # field value operator based parsing,
                            # '#<value operator method>:expected_value:expected_result#'
                            field_value_operator_match = re.match("#(.*):(.*):(.*)#", parser_value)

                            if operator_module_match:
                                operator_method_name = operator_module_match.groups()[0]
                                expected_value = operator_module_match.groups()[1]
                                expected_result = operator_module_match.groups()[2]

                                operator_method = getattr(operator, operator_method_name)
                                # match the value of the manifest field against the expected value
                                field_value_match = operator_method(field_value, expected_value)

                            if field_value_operator_match:
                                operator_method_name = field_value_operator_match.groups()[0]
                                expected_value = field_value_operator_match.groups()[1]
                                expected_result = field_value_operator_match.groups()[2]

                                operator_method = getattr(field_value, operator_method_name)
                                # match the value of the manifest field against the expected value
                                field_value_match = operator_method(expected_value)

                            # if this is not a boolean get the expected result from the info
                            if not isinstance(field_value_match, bool):
                                value_type = type(field_value_match)
                                try:
                                    field_value_match = (field_value_match == value_type(expected_result))
                                except:
                                    field_value_match = False

                            if field_value_match:
                                # drop the value of resolution order by that much amount
                                match_score += 1

                            self.logger.info("Manifest field filter info for field %s." % field,
                                             extra={
                                                  "action_show_more_info": {
                                                      "label": "Show Data",
                                                      "tooltip": "Show the data",
                                                      "text": "Value: %s\nParser String: %s"
                                                              "\nOperator Method: %s\nExpected Value: %s"
                                                              "\nMatch Score: %s\nExpected Result: %s"
                                                              "\nPath: %s\nManifest Fields: %s" %
                                                              (field_value, parser_value, operator_method,
                                                               expected_value, match_score, expected_result, path,
                                                               pprint.pformat(manifest_file_fields))
                                                  }
                                              })

                    # if all the conditions match, only then we need to update the resolution order
                    # else drop the priority of this item type to last so a normal item type will get picked, this is
                    # to maintain backwards compatibility.
                    if match_score == len(manifest_field_filters.keys()):
                        found_matching_manifest_filter = True
                        # TODO: See if this needs to be changed to use highest resolution oreder instead of items'
                        resolution_order = resolution_order - match_score
                    else:
                        resolution_order = resolution_order + max_resolution_order
                # add the mapping with the updated resolution order, if any.
                filtered_template_item_type_mapping.append((resolution_order, work_path_template, item_type))

        # in case of non manifest based ingestion, item types with type info containing manifest_field_filters
        # will be removed from the mapping list, if they don't have a matching work_path_template.
        else:
            for resolution_order, work_path_template, item_type in template_item_type_mapping:
                type_info = self._get_item_type_info(settings, item_type)
                if not type_info["manifest_field_filters"]:
                    filtered_template_item_type_mapping.append((resolution_order, work_path_template, item_type))

        # sort the list on resolution_order, giving preference to a matching template
        filtered_template_item_type_mapping.sort(
            key=lambda elem: elem[0] if not elem[1] else elem[0]-max_resolution_order)

        return filtered_template_item_type_mapping

    def _get_item_context_from_path(self, work_path_template, path, parent_item, default_entities=list()):
        """Updates the context of the item from the work_path_template/template, if needed.

        :param work_path_template: The work_path template name
        :param parent_item: parent item instance
        :param default_entities: a list of default entities to use during the creation of the
        :class:`sgtk.Context` if not found in the path
        """
        publisher = self.parent

        work_tmpl = publisher.get_template_by_name(work_path_template)
        if work_tmpl and isinstance(work_tmpl, tank.template.TemplateString):
            # use file name if we got TemplateString
            path = os.path.basename(path)

        context = super(IngestCollectorPlugin, self)._get_item_context_from_path(work_path_template,
                                                                                 path,
                                                                                 parent_item,
                                                                                 default_entities)
        if context.entity:
            # if the context already has a valid step use that.
            # we extract the step from the work_path_template, in case of notes.
            if not context.step:
                step_filters = list()
                step_filters.append(['short_name', 'is', "vendor"])

                # make sure we get the correct Step!
                # this should handle whether the Step is from Sequence/Shot/Asset
                step_filters.append(["entity_type", "is", context.entity["type"]])

                fields = ['entity_type', 'code', 'id', 'name']

                # add a vendor step to all ingested files
                step_entity = self.sgtk.shotgun.find_one(
                    entity_type='Step',
                    filters=step_filters,
                    fields=fields
                )
            else:
                step_entity = context.step

            if step_entity:
                default_entities = [step_entity]
                # FIXME: step entity in context has "name" and entity queried from shotgun has "code"
                content = step_entity["name"] if step_entity.get("name") else step_entity["code"]

                task_filters = [
                    ['step', 'is', step_entity],
                    ['entity', 'is', context.entity],
                    ['project', 'is', context.project],
                    ['content', 'is', content]
                ]

                task_fields = ['content', 'entity_type', 'id']

                task_entity = self.sgtk.shotgun.find_one(
                    entity_type='Task',
                    filters=task_filters,
                    fields=task_fields
                )

                # create the task:
                if not task_entity:

                    data = {
                        "step": step_entity,
                        "project": context.project,
                        "entity": context.entity,
                        "content": content,
                        "sg_status_list": "na"
                    }

                    task_entity = self.sgtk.shotgun.create("Task", data, return_fields=task_fields)
                    if not task_entity:
                        self.logger.error("Failed to create Ingestion Task.",
                                          extra={
                                              "action_show_more_info": {
                                                  "label": "Show Data",
                                                  "tooltip": "Show the error log",
                                                  "text": "Data: %s\nPath: %s" % (pprint.pformat(data),
                                                                                  path)
                                              }
                                          })

                if task_entity:
                    # try to set the status of the task entity to na
                    try:
                        self.sgtk.shotgun.update("Task", task_entity["id"], {"sg_status_list": "na"})
                    except:
                        pass

                    default_entities.append(task_entity)

                context = super(IngestCollectorPlugin, self)._get_item_context_from_path(work_path_template,
                                                                              path,
                                                                              parent_item,
                                                                              default_entities)

        return context

    def _get_work_path_template_from_settings(self, settings, item_type, path):
        """
        Helper method to get the work_path_template from the collector settings object.
        """
        # first try with filename
        work_path_template = super(IngestCollectorPlugin, self)._get_work_path_template_from_settings(settings,
                                                                                                      item_type,
                                                                                                      os.path.basename(path))
        if work_path_template:
            return work_path_template

        return super(IngestCollectorPlugin, self)._get_work_path_template_from_settings(settings,
                                                                                        item_type,
                                                                                        path)

    def _get_template_fields_from_path(self, item, template_name, path):
        """
        Get the fields by parsing the input path using the template derived from
        the input template name.
        """

        work_path_template = item.properties.get("work_path_template")

        if work_path_template:
            work_tmpl = self.parent.get_template_by_name(work_path_template)
            if work_tmpl and isinstance(work_tmpl, tank.template.TemplateString):
                # use file name if the path was parsed using TemplateString
                path = os.path.basename(path)

        fields = super(IngestCollectorPlugin, self)._get_template_fields_from_path(item,
                                                                                   template_name,
                                                                                   path)
        # adding a description to item
        item.description = "Created by shotgun_ingest on %s" % str(datetime.date.today())
        return fields
