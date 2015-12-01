'''
@author: rcattiau
'''

from common_unit_test import UnitTestCase
from nxdrive.tests.common_unit_test import log
from nxdrive.tests.common_unit_test import FILE_CONTENT
from nose.plugins.skip import SkipTest
from math import floor, log10
from copy import copy

import os
import shutil


class VolumeTestCase(UnitTestCase):

    NUMBER_OF_LOCAL_FILES = 10
    SYNC_TIMEOUT = 100  # in seconds

    def pow10floor(self, x):
        return int(floor(log10(float(x)))+1)

    def create_tree(self, folders, files, depth, parent):
        if depth <= 0:
            return
        for folder in range(1, folders+1):
            foldername = self.get_name(True, self.depth-depth+1, folder)
            folderobj = dict()
            folderobj["path"] = os.path.join(parent["path"], foldername)
            if not self.fake:
                self.local_client_1.make_folder(parent["path"], foldername)
            folderobj["name"] = foldername
            folderobj["childs"] = dict()
            parent["childs"][foldername] = folderobj
            self.items = self.items + 1
            self.create_tree(folders, files, depth-1, folderobj)
            for file in range(1, files+1):
                filename = self.get_name(False, self.depth-depth+1, file)
                folderobj["childs"][filename]=dict()
                folderobj["childs"][filename]["name"]=filename
                path = os.path.join(folderobj["path"], filename)
                if not self.fake:
                    self.local_client_1.make_file(folderobj["path"], filename, FILE_CONTENT)
                self.items = self.items + 1

    '''
    '''
    def setUp(self):
        super(VolumeTestCase, self).setUp()
        self.fake = False
        if not self.fake:
            self.engine_1.start()
            self.wait_sync()
            self.engine_1.stop()
        self.items = 0
        values = None
        if "TEST_VOLUME" in os.environ:
            values = os.environ["TEST_VOLUME"].split(",")
        if values is None or len(values) < 3:
            # Low volume by default to stick to 1h
            values = "3, 10, 3".split(",")
        self.fmt = ["", "", ""]
        for i in range(0,3):
            self.fmt[i] = "%0" + str(self.pow10floor(values[i])) + "d"
        self.depth = int(values[2])
        self.num_files = int(values[1])
        self.num_folders = int(values[0])
        self.tree = dict()
        self.tree["childs"] = dict()
        self.tree["path"] = "/"
        log.debug("Generating in: " + self.local_client_1._abspath('/'))
        self.create_tree(self.num_folders, self.num_files, self.depth, self.tree)
        log.debug("Generated done in: " + self.local_client_1._abspath('/'))
        if not self.fake:
            log.debug('*** engine1 starting')
            self.engine_1.start()
            self.wait_sync(timeout=self.items)
            log.debug('*** engine 1 synced')

    def get_name(self, folder, depth, number):
        if folder:
            return unicode(("folder_"+self.fmt[2]+"_"+self.fmt[0]) % (depth, number))
        else:
            return unicode(("file_"+self.fmt[2]+"_"+self.fmt[1] + ".txt") % (depth, number))

    def get_path(self, folder, depth, number):
        child = ""
        for i in range(self.depth + 1 - depth, self.depth + 1):
            if i == 1 and not folder:
                child = self.get_name(False, self.depth-i+1, number)
            child = os.path.join(self.get_name(True, self.depth-i+1, number), child)
        return "/" + child

    def _check_folder(self, path, removed=[], added=[]):
        if path[-1] == "/":
            path = path[0:-1]
        # First get the remote id
        remote_id = self.local_client_1.get_remote_id(path)
        self.assertIsNotNone(remote_id, "Should have a remote id")

        # get depth
        depth = int(os.path.basename(path).split("_")[1])

        # calculated expected children
        children = dict()
        if depth != self.depth:
            for i in range(1, self.num_folders+1):
                children[self.get_name(True, depth+1, i)]=True
        for i in range(1, self.num_files+1):
            children[self.get_name(False, depth, i)]=True
        for name in removed:
            if name in children:
                del children[name]
        for name in added:
            children[name]=True
        remote_refs = dict()

        # check locally
        os_children = os.listdir(self.local_client_1._abspath(path))
        self.assertEquals(len(os_children), len(children))
        cmp_children = copy(children)
        for name in os_children:
            if name not in cmp_children:
                self.fail("Not expected local child '" + name + "' in " + path)
            remote_ref = self.local_client_1.get_remote_id(os.path.join(path, name))
            self.assertIsNotNone(remote_ref, "Sync is done should not be None remote_ref")
            remote_refs[remote_ref]=name
            del cmp_children[name]
        # compare each name
        self.assertEquals(0, len(cmp_children), "Expected local child in " + path + ": not present are " + ', '.join(cmp_children.values()))

        # check remotely
        remote_children = self.remote_file_system_client_1.get_children_info(remote_id)
        self.assertEquals(len(remote_children), len(children))
        for child in remote_children:
            if child.uid not in remote_refs:
                self.fail("Not expected remote child '" + child.name + "' in " + path)
            self.assertEquals(child.name, remote_refs[child.uid])

    def test_moves(self):
        self._moves()

    def test_moves_stopped(self):
        self._moves(stopped=True)

    def _moves(self, stopped=False):
        if stopped and not self.fake:
            self.engine_1.stop()
        # While we are started
        # Move one parent to the second children
        if len(self.tree["childs"]) < 3 or self.depth < 2:
            raise SkipTest("Can't execute this test on so few data")
        # Move root 2 in, first subchild of 1
        root_2 = self.get_path(True, 1, 2)
        child = self.get_path(True, 3, 1)
        log.debug("Will mode " + root_2 + " into " + child)
        if not self.fake:
            shutil.move(self.local_client_1._abspath(root_2), self.local_client_1._abspath(child))
        root_1 = self.get_path(True, 1, 1)
        root_3 = self.get_path(True, 1, 3)
        log.debug("Will mode " + root_1 + " into " + root_3)
        if not self.fake:
            shutil.move(self.local_client_1._abspath(root_1), self.local_client_1._abspath(root_3))
        # Update paths
        child = "/" + self.get_name(True, 1, 3) + child
        root_2 = child + self.get_name(True, 1, 2)
        root_1 = root_3 + self.get_name(True, 1, 1)
        if stopped and not self.fake:
            self.engine_1.start()
        self.wait_sync(wait_for_async=True, timeout=self.items)
        # Assert
        self._check_folder(root_3, added=[self.get_name(True, 1, 1)])
        self._check_folder(child, added=[self.get_name(True, 1, 2)])
        self._check_folder(root_1)
        self._check_folder(root_2)

    def test_copies(self):
        self._copies()

    def test_copies_stopped(self):
        self._copies(stopped=True)

    def _copies(self, stopped=False):
        if stopped and not self.fake:
            self.engine_1.stop()

        # Move root 2 in, first subchild of 1
        root_2 = self.get_path(True, 1, 2)
        child = self.get_path(True, 3, 1)
        log.debug("Will mode " + root_2 + " into " + child)
        if not self.fake:
            shutil.copytree(self.local_client_1._abspath(root_2), self.local_client_1._abspath(child + self.get_name(True, 1, 2)))
        root_1 = self.get_path(True, 1, 1)
        root_3 = self.get_path(True, 1, 3)
        log.debug("Will mode " + root_1 + " into " + root_3)
        if not self.fake:
            shutil.copytree(self.local_client_1._abspath(root_1), self.local_client_1._abspath(root_3+  self.get_name(True, 1, 1)))
        # Update paths
        child = "/" + self.get_name(True, 1, 3) + child
        root_2 = child + self.get_name(True, 1, 2)
        root_1 = root_3 + self.get_name(True, 1, 1)
        root_1_path = self.local_client_1._abspath(root_1)
        child_path = self.local_client_1._abspath(child)
        added_files = []
        # Copies files from one folder to another
        for name in os.listdir(child_path):
            if not os.path.isfile(os.path.join(child_path, name)):
                continue
            shutil.copy(os.path.join(child_path, name), root_1_path)
            added_files.append(name)

        if stopped and not self.fake:
            self.engine_1.start()
        self.wait_sync(wait_for_async=True, timeout=self.items)
        # Assert
        self._check_folder(root_3, added=[self.get_name(True, 1, 1)])
        self._check_folder(child, added=[self.get_name(True, 1, 2)])
        self._check_folder(root_1, added=added_files)
        self._check_folder(root_2)
        # check original copied
        self._check_folder(self.get_path(True, 1, 1))
        self._check_folder(self.get_path(True, 1, 2))