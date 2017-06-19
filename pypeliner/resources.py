import os
import pickle
import shutil
import logging

import pypeliner.helpers
import pypeliner.identifiers
import pypeliner.fstatcache


class OutputMissingException(Exception):
    def __init__(self, filename):
        self.filename = filename
    def __str__(self):
        return 'expected output {0} missing'.format(self.filename)


class Dependency(object):
    """ An input/output in the dependency graph
    
    This class is mainly used for tracking dependencies in the
    dependency graph for which it is not appropriate to check
    timestamps, in particular for an axis chunk input to a job
    parallelized on that axis.
    """
    is_temp = False
    def __init__(self, name, node):
        self.name = name
        self.node = node
    @property
    def id(self):
        return (self.name, self.node)
    @property
    def exists(self):
        return True
    def build_displayname(self, base_node=pypeliner.identifiers.Node()):
        name = '/' + self.name
        if self.node.displayname != '':
            name = '/' + self.node.displayname + name
        if base_node.displayname != '':
            name = '/' + base_node.displayname + name
        return name
    def cleanup(self):
        pass


class Resource(Dependency):
    """ Abstract input/output in the dependency graph
    associated with a file tracked using creation time """
    def build_displayname_filename(self, base_node=pypeliner.identifiers.Node()):
        displayname = self.build_displayname(base_node)
        if displayname != self.filename:
            return ' '.join([displayname, self.filename])
        else:
            return displayname
    @property
    def exists(self):
        raise NotImplementedError
    @property
    def createtime(self):
        raise NotImplementedError
    def touch(self):
        raise NotImplementedError


def _check_template(template, node):
    for axis, _ in node:
        if axis not in template:
            raise ValueError('filename template {} does not contain {{{}}}'.format(template, axis))


def resolve_user_filename(name, node, fnames=None, template=None):
    """ Resolve a filename based on user provided information """
    fname_key = tuple([a[1] for a in node])
    if fnames is not None:
        if len(fname_key) == 1:
            filename = fnames.get(fname_key[0], name)
        else:
            filename = fnames.get(fname_key, name)
    elif template is not None:
        _check_template(template, node)
        filename = template.format(**dict(node))
    else:
        _check_template(name, node)
        try:
            filename = name.format(**dict(node))
        except KeyError as e:
            raise ValueError('template {} contains {}'.format(name, e.args[0]))
    return filename


class UserResource(Resource):
    """ A file resource with filename and creation time if created """
    def __init__(self, name, node, filename):
        self.name = name
        self.node = node
        self.filename = filename
        pypeliner.fstatcache.invalidate_cached_state(self.filename)
    def build_displayname(self, base_node=pypeliner.identifiers.Node()):
        return self.filename
    @property
    def exists(self):
        return pypeliner.fstatcache.get_exists(self.filename)
    @property
    def createtime(self):
        return pypeliner.fstatcache.get_createtime(self.filename)
    def touch(self):
        if not self.exists:
            raise Exception('cannot touch missing user output')
        pypeliner.fstatcache.invalidate_cached_state(self.filename)
        pypeliner.helpers.touch(self.filename)
    def finalize(self, write_filename):
        try:
            pypeliner.fstatcache.invalidate_cached_state(self.filename)
            os.rename(write_filename, self.filename)
        except OSError:
            raise OutputMissingException(write_filename)


class TempFileResource(Resource):
    """ A file resource with filename and creation time if created """
    def __init__(self, name, node, filename):
        self.name = name
        self.node = node
        self.filename = filename
        self.is_temp = True
        self.placeholder_filename = self.filename + '._placeholder'
        pypeliner.fstatcache.invalidate_cached_state(self.filename)
        pypeliner.fstatcache.invalidate_cached_state(self.placeholder_filename)
    def _save_createtime(self):
        pypeliner.fstatcache.invalidate_cached_state(self.placeholder_filename)
        pypeliner.helpers.saferemove(self.placeholder_filename)
        pypeliner.helpers.touch(self.placeholder_filename)
        shutil.copystat(self.filename, self.placeholder_filename)
    @property
    def exists(self):
        return pypeliner.fstatcache.get_exists(self.filename)
    @property
    def createtime(self):
        if pypeliner.fstatcache.get_exists(self.filename):
            return pypeliner.fstatcache.get_createtime(self.filename)
        if pypeliner.fstatcache.get_exists(self.placeholder_filename):
            return pypeliner.fstatcache.get_createtime(self.placeholder_filename)
    def touch(self):
        if self.exists:
            pypeliner.fstatcache.invalidate_cached_state(self.filename)
            pypeliner.helpers.touch(self.filename)
            self._save_createtime()
        else:
            pypeliner.fstatcache.invalidate_cached_state(self.placeholder_filename)
            pypeliner.helpers.touch(self.placeholder_filename)
    def finalize(self, write_filename):
        try:
            pypeliner.fstatcache.invalidate_cached_state(self.filename)
            os.rename(write_filename, self.filename)
        except OSError:
            raise OutputMissingException(write_filename)
        self._save_createtime()
    def cleanup(self):
        if self.exists:
            logging.getLogger('resources').debug('removing ' + self.filename)
            pypeliner.fstatcache.invalidate_cached_state(self.filename)
            os.remove(self.filename)


class TempObjResource(Resource):
    """ A file resource with filename and creation time if created """
    def __init__(self, name, node, filename, is_input=True):
        self.name = name
        self.node = node
        self.filename = filename + ('._i', '._o')[is_input]
        self.is_input = is_input
        self.is_temp = True
        pypeliner.fstatcache.invalidate_cached_state(self.filename)
    @property
    def exists(self):
        return pypeliner.fstatcache.get_exists(self.filename)
    @property
    def createtime(self):
        return pypeliner.fstatcache.get_createtime(self.filename)
    def touch(self):
        if not self.exists:
            raise Exception('cannot touch missing object')
        pypeliner.fstatcache.invalidate_cached_state(self.filename)
        pypeliner.helpers.touch(self.filename)


def obj_equal(obj1, obj2):
    try:
        equal = obj1.__eq__(obj2)
        if equal is not NotImplemented:
            return equal
    except AttributeError:
        pass
    if obj1.__class__ != obj2.__class__:
        return False
    try:
        return obj1.__dict__ == obj2.__dict__
    except AttributeError:
        pass
    return obj1 == obj2


class TempObjManager(object):
    """ A file resource with filename and creation time if created """
    def __init__(self, name, node, filename):
        self.name = name
        self.node = node
        self.input = TempObjResource(name, node, filename, is_input=True)
        self.output = TempObjResource(name, node, filename, is_input=False)
    def get_obj(self):
        try:
            with open(self.input.filename, 'rb') as f:
                return pickle.load(f)
        except IOError as e:
            if e.errno == 2:
                pass
    def finalize(self, obj):
        with open(self.output.filename, 'wb') as f:
            pickle.dump(obj, f)
        if not self.input.exists or not obj_equal(obj, self.get_obj()):
            with open(self.input.filename, 'wb') as f:
                pickle.dump(obj, f)
        pypeliner.fstatcache.invalidate_cached_state(self.input.filename)
        pypeliner.fstatcache.invalidate_cached_state(self.output.filename)


