"""
Hook for doing any preprocessing to the burnin nuke script.
"""
import sgtk
import datetime
import os
import hashlib
import re
import time

HookBaseClass = sgtk.get_hook_baseclass()

class PreprocessNuke(HookBaseClass):

    def get_processed_script(self, nuke_script_path, **kwargs):
        replace_data = kwargs.get("fields", {})

        if replace_data.get("path"):
            # TODO: publisher.util.get_publish_name() does this much better
            replace_data["file_base_name"] = os.path.basename(replace_data["path"]).split('.')[0]

        context = self.parent.context
        if context.entity:
            sg_entity_type = context.entity["type"]
            sg_filters = [["id", "is", context.entity["id"]]]

            sg_fields = self.parent.get_setting('entity_burnin_sg_fields')
            replace_data.update(self.parent.shotgun.find_one(sg_entity_type,
                                                      filters=sg_filters,
                                                      fields=sg_fields))
        if context.task:
            sg_fields = self.parent.get_setting('task_burnin_sg_fields')
            if 'duration' in sg_fields and 'time_logs_sum' in sg_fields:
                sg_data = self.parent.shotgun.find('Task', filters=[['entity', 'is', context.entity],
                                                                    ['step', 'is', context.step]],
                                                   fields=['duration', 'time_logs_sum'])
                total_duration = 0
                total_time_logged = 0
                for data in sg_data:
                    total_duration += data['duration'] if data['duration'] else 0
                    total_time_logged += data['time_logs_sum'] if data['time_logs_sum'] else 0
                if total_duration: total_duration = str(total_duration/(8.0 * 60.0)) + ' day(s)'
                if total_time_logged: total_time_logged = str(total_time_logged/(8.0 * 60.0)) + ' day(s)'

                replace_data.update({'duration': total_duration})
                replace_data.update({'time_logs_sum': total_time_logged})

                sg_fields = list(set(sg_fields) - set(['duration', 'time_logs_sum']))

            task = self.parent.shotgun.find_one('Task', filters=[['entity', 'is', context.entity],
                                                                 ['id', 'is', context.task['id']]],
                                                fields=sg_fields)
            replace_data.update(task)

        if not replace_data:
            # nothing to replace, nothing to do here
            return nuke_script_path

        tmp_file_prefix = "reviewsubmission_tmp_nuke_script"
        tmp_file_name = "%s_%s.nk" % (tmp_file_prefix, hashlib.md5(str(time.time())).hexdigest())
        processed_script_path = os.path.join("/var", "tmp", tmp_file_name)

        self.parent.log_debug("Saving nuke script to: {}".format(processed_script_path))
        with open(nuke_script_path, 'r') as source_script_file, open(processed_script_path,
                                                                    'w') as tmp_script_file:
            nuke_script_text = source_script_file.read()
            nuke_script_text = self._replace_vars(nuke_script_text, replace_data)
            tmp_script_file.write(nuke_script_text)

        return processed_script_path

    @staticmethod
    def remove_html(string):
        return re.sub('<.+?>', '', string)

    def _replace_vars(self, attr, data):
        """
        Replace the variables in a nuke script
        Variables defined by [* *] or \[* *]
        """
        # get rid of nukes escape characters (fancy, huh)
        attr = attr.replace("\[*", "[*")

        # look for anything with a [* *] pattern
        vars = re.compile("\[\*[A-Za-z_ %/:0-9()\-,.\+]+\*\]").findall(attr)

        dt = datetime.datetime.now()

        for var in vars:
            var_tmp = var.replace("[*", "").replace("*]", "")
            # Replace the date/time variables
            if var_tmp.startswith('date '):
                date_str = var_tmp.replace('date ', '')
                attr = attr.replace(var, dt.strftime(date_str))

            # Replace the frame number variables
            elif (var_tmp.lower() == "numframes" and
                          data.get('first_frame') != None and data.get('first_frame') != '' and
                          data.get('last_frame') != None and data.get('last_frame') != ''):
                range = str(int(data.get('lf')) - int(data.get('first_frame')))
                attr = attr.replace(var, range)

            # and the increment that may be at the end of the frame number
            elif "+" in var_tmp.lower():
                (tmp, num) = var_tmp.split("+")
                sum = str(int(data.get(tmp)) + int(num))
                attr = attr.replace(var, sum)

            # make it easier to enter screen coordinates
            # that vary with resolution, by normalizing to
            # (-0.5 -0.5) to (0.5 0.5)
            elif "screenspace" in var_tmp.lower():
                var_tmp = var_tmp.replace("(", " ").replace(",", " ").replace(")", " ")
                (key, xString, yString) = var_tmp.split()
                xFloat = float(xString) + 0.5
                yFloat = float(yString) + 0.5
                translateString = (
                "{{SHUFFLE_CONSTANT.actual_format.width*(%s) i} {SHUFFLE_CONSTANT.actual_format.height*(%s) i}}" % (
                str(xFloat), str(yFloat)))
                attr = attr.replace(var, translateString)

            # TODO: do we handle this differently?
            # Replace the showname
            # (now resolved in resolveMainProcessVariables)
            elif var_tmp == "showname":
                attr = attr.replace(var, str(data.get('showname')))

            # remove knobs that have a [**] value but nothing in data
            elif (data.get(var_tmp) == '' or
                          data.get(var_tmp) == None or
                          data.get(var_tmp) == "None"):
                regexp = ".*\[\*"
                regexp += var_tmp
                regexp += "\*\].*"
                line = re.compile(regexp).findall(attr)
                if line != None and len(line) > 0:
                    if line[0].count('message') > 0:
                        attr = attr.replace(var, str('""'))
                    else:
                        attr = attr.replace(var, "None")

            else:
                replaceval = self.remove_html(str(data.get(var_tmp)))
                if (replaceval == ""):
                    replaceval == '""'
                attr = attr.replace(var, str(replaceval))

        return attr
    # end replaceVars