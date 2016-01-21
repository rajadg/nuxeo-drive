import time
import urllib2
import socket

from nxdrive.tests.common import TEST_WORKSPACE_PATH
from nxdrive.tests.common import OS_STAT_MTIME_RESOLUTION
from nxdrive.tests.common_unit_test import UnitTestCase
from nxdrive.client import LocalClient
from nxdrive.tests import RemoteTestClient
from nxdrive.client.remote_filtered_file_system_client import RemoteFilteredFileSystemClient


class TestSynchronization(UnitTestCase):

    def test_binding_initialization_and_first_sync(self):
        local = self.local_client_1
        remote = self.remote_document_client_1

        # Create some documents in a Nuxeo workspace and bind this server to a
        # Nuxeo Drive local folder
        self.make_server_tree()

        # The root binding operation does not create the local folder yet.
        self.assertFalse(local.exists('/'))

        # Launch ndrive and check synchronization
        self.engine_1.start()
        self.wait_sync(wait_for_async=True)
        self.assertTrue(local.exists('/'))
        self.assertTrue(local.exists('/Folder 1'))
        self.assertEquals(local.get_content('/Folder 1/File 1.txt'), "aaa")
        self.assertTrue(local.exists('/Folder 1/Folder 1.1'))
        self.assertEquals(local.get_content('/Folder 1/Folder 1.1/File 2.txt'), "bbb")
        self.assertTrue(local.exists('/Folder 1/Folder 1.2'))
        self.assertEquals(local.get_content('/Folder 1/Folder 1.2/File 3.txt'), "ccc")
        self.assertTrue(local.exists('/Folder 2'))
        # Cannot predicte the resolution in advance
        self.assertTrue(remote.get_content(self._duplicate_file_1), "Some content.")
        self.assertTrue(remote.get_content(self._duplicate_file_2), "Other content.")
        if local.get_content('/Folder 2/Duplicated File.txt') == "Some content.":
            self.assertEquals(local.get_content('/Folder 2/Duplicated File__1.txt'), "Other content.")
        else:
            self.assertEquals(local.get_content('/Folder 2/Duplicated File.txt'), "Other content.")
            self.assertEquals(local.get_content('/Folder 2/Duplicated File__1.txt'), "Some content.")
        self.assertEquals(local.get_content('/Folder 2/File 4.txt'), "ddd")
        self.assertEquals(local.get_content('/File 5.txt'), "eee")

        # Unbind root and resynchronize
        remote.unregister_as_root(self.workspace)
        self.wait_sync(wait_for_async=True)
        self.assertFalse(local.exists('/'))

    def test_binding_synchronization_empty_start(self):
        local = self.local_client_1
        remote = self.remote_document_client_1

        # Let's create some documents on the server and launch first synchronization
        self.make_server_tree()
        self.engine_1.start()
        self.wait_sync(wait_for_async=True)

        # We should now be fully synchronized
        folder_count, file_count = self.get_local_child_count(self.local_nxdrive_folder_1)
        self.assertEquals(folder_count, 5)
        self.assertTrue(file_count, 7)

        # Wait a bit for file time stamps to increase enough: on OSX HFS+ the
        # file modification time resolution is 1s for instance
        time.sleep(OS_STAT_MTIME_RESOLUTION)

        # Let do some local and remote changes concurrently
        local.delete('/File 5.txt')
        local.update_content('/Folder 1/File 1.txt', 'aaaa')
        local.make_folder('/', 'Folder 4')

        # The remote client used in this test is handling paths relative to
        # the 'Nuxeo Drive Test Workspace'
        remote.update_content('/Folder 1/Folder 1.1/File 2.txt', 'bbbb')
        remote.delete('/Folder 2')
        f3 = remote.make_folder(self.workspace, 'Folder 3')
        remote.make_file(f3, 'File 6.txt', content='ffff')

        # Launch synchronization
        self.wait_sync(wait_for_async=True)

        # We should now be fully synchronized again
        self.assertFalse(remote.exists('/File 5.txt'))
        self.assertEquals(remote.get_content('/Folder 1/File 1.txt'), "aaaa")
        self.assertTrue(remote.exists('/Folder 4'))

        self.assertEquals(local.get_content('/Folder 1/Folder 1.1/File 2.txt'), "bbbb")
        # Let's just check remote document hasn't changed
        self.assertEquals(remote.get_content('/Folder 1/Folder 1.1/File 2.txt'), "bbbb")
        self.assertFalse(local.exists('/Folder 2'))
        self.assertTrue(local.exists('/Folder 3'))
        self.assertEquals(local.get_content('/Folder 3/File 6.txt'), "ffff")

        # Send some binary data that is not valid in utf-8 or ascii
        # (to test the HTTP transform layer).
        time.sleep(OS_STAT_MTIME_RESOLUTION)
        local.update_content('/Folder 1/File 1.txt', "\x80")
        remote.update_content('/Folder 1/Folder 1.1/File 2.txt', '\x80')

        self.wait_sync(wait_for_async=True)

        self.assertEquals(remote.get_content('/Folder 1/File 1.txt'), "\x80")
        self.assertEquals(local.get_content('/Folder 1/Folder 1.1/File 2.txt'), "\x80")
        # Let's just check remote document hasn't changed
        self.assertEquals(remote.get_content('/Folder 1/Folder 1.1/File 2.txt'), "\x80")

    def test_single_quote_escaping(self):
        remote = self.remote_document_client_1
        local = self.local_client_1

        remote.unregister_as_root(self.workspace)
        self.engine_1.start()
        remote.make_folder('/', "APPEL D'OFFRES")
        remote.register_as_root("/APPEL D'OFFRES")
        self.wait_sync(wait_for_async=True)
        self.assertTrue(local.exists("/APPEL D'OFFRES"))

        remote.unregister_as_root("/APPEL D'OFFRES")
        self.wait_sync(wait_for_async=True)
        self.assertFalse(local.exists("/APPEL D'OFFRES"))

    def test_synchronization_modification_on_created_file(self):
        # Regression test: a file is created locally, then modification is
        # detected before first upload
        local = self.local_client_1
        self.assertFalse(local.exists('/'))

        self.engine_1.start()
        self.wait_sync(wait_for_async=True)
        self.assertTrue(local.exists('/'))
        self.engine_1.stop()

        # Let's create some documents on the client and the server
        local.make_folder('/', 'Folder')
        local.make_file('/Folder', 'File.txt', content='Some content.')

        # First local scan (assuming the network is offline):
        self.queue_manager_1.suspend()
        self.queue_manager_1._disable = True
        self.engine_1.start()
        self.wait_sync(timeout=5, fail_if_timeout=False)
        workspace_children = self.engine_1.get_dao().get_local_children('/' + self.workspace_title)
        self.assertEquals(len(workspace_children), 1)
        self.assertEquals(workspace_children[0].pair_state, 'locally_created')
        folder_children = self.engine_1.get_dao().get_local_children('/' + self.workspace_title + '/Folder')
        self.assertEquals(len(folder_children), 1)
        self.assertEquals(folder_children[0].pair_state, 'locally_created')

        # Wait a bit for file time stamps to increase enough: on most OS
        # the file modification time resolution is 1s
        time.sleep(OS_STAT_MTIME_RESOLUTION)

        # Let's modify it offline and wait for a bit
        local.update_content('/Folder/File.txt', content='Some content.')
        self.wait_sync(timeout=5, fail_if_timeout=False)
        # File has not been synchronized, it is still in the locally_created state
        file_state = self.engine_1.get_dao().get_state_from_local('/' + self.workspace_title + '/Folder/File.txt')
        self.assertEquals(file_state.pair_state, 'locally_created')

        # Assume the computer is back online, the synchronization should occur
        # as if the document was just created and not trigger an update
        self.queue_manager_1._disable = False
        self.queue_manager_1.resume()
        self.wait_sync()
        folder_state = self.engine_1.get_dao().get_state_from_local('/' + self.workspace_title + '/Folder')
        self.assertEquals(folder_state.pair_state, 'synchronized')
        file_state = self.engine_1.get_dao().get_state_from_local('/' + self.workspace_title + '/Folder/File.txt')
        self.assertEquals(file_state.pair_state, 'synchronized')

    def test_basic_synchronization(self):
        local = self.local_client_1
        remote = self.remote_document_client_1
        self.engine_1.start()
        self.wait_sync(wait_for_async=True)

        # Let's create some document on the client and the server
        local.make_folder('/', 'Folder 3')
        self.make_server_tree()

        # Launch ndrive and check synchronization
        self.wait_sync(wait_for_async=True)
        self.assertTrue(remote.exists('/Folder 3'))
        self.assertTrue(local.exists('/Folder 1'))
        self.assertTrue(local.exists('/Folder 2'))
        self.assertTrue(local.exists('/File 5.txt'))

    def test_synchronization_skip_errors(self):
        local = self.local_client_1
        self.assertFalse(local.exists('/'))

        # Perform first scan and sync
        self.engine_1.start()
        self.wait_sync(wait_for_async=True)
        self.assertTrue(local.exists('/'))
        self.engine_1.stop()

        # Let's create some documents on the client and the server
        local.make_folder('/', 'Folder 3')
        self.make_server_tree()

        # Detect the files to synchronize but do not perform the
        # synchronization
        self.queue_manager_1.suspend()
        self.queue_manager_1._disable = True
        self.engine_1.start()
        self.wait_sync(wait_for_async=True, timeout=5, fail_if_timeout=False)

        workspace_children = self.engine_1.get_dao().get_local_children('/' + self.workspace_title)
        self.assertEquals(len(workspace_children), 4)
        sorted_children = sorted(workspace_children, key=lambda x: x.local_path)
        self.assertEquals(sorted_children[0].remote_name, 'File 5.txt')
        self.assertEquals(sorted_children[0].pair_state, 'remotely_created')
        self.assertEquals(sorted_children[1].remote_name, 'Folder 1')
        self.assertEquals(sorted_children[1].pair_state, 'remotely_created')
        self.assertEquals(sorted_children[2].remote_name, 'Folder 2')
        self.assertEquals(sorted_children[2].pair_state, 'remotely_created')
        self.assertEquals(sorted_children[3].local_name, 'Folder 3')
        self.assertEquals(sorted_children[3].pair_state, 'locally_created')

        # Simulate synchronization errors
        file_5_state = sorted_children[0]
        folder_3_state = sorted_children[3]
        self.engine_1.get_local_watcher().increase_error(file_5_state, 'TEST_FILE_ERROR')
        self.engine_1.get_local_watcher().increase_error(folder_3_state, 'TEST_FILE_ERROR')

        # Run synchronization
        self.queue_manager_1._disable = False
        self.queue_manager_1.resume()
        self.wait_sync(enforce_errors=False)

        # All errors have been skipped, while the remaining docs have
        # been synchronized
        file_5_state = self.engine_1.get_dao().get_normal_state_from_remote(file_5_state.remote_ref)
        self.assertEquals(file_5_state.pair_state, 'remotely_created')
        folder_3_state = self.engine_1.get_dao().get_state_from_local(folder_3_state.local_path)
        self.assertEquals(folder_3_state.pair_state, 'locally_created')
        folder_1_state = self.engine_1.get_dao().get_normal_state_from_remote(sorted_children[1].remote_ref)
        self.assertEquals(folder_1_state.pair_state, 'synchronized')
        folder_2_state = self.engine_1.get_dao().get_normal_state_from_remote(sorted_children[2].remote_ref)
        self.assertEquals(folder_2_state.pair_state, 'synchronized')

        # Retry synchronization of pairs in error
        self.wait_sync()
        file_5_state = self.engine_1.get_dao().get_normal_state_from_remote(file_5_state.remote_ref)
        self.assertEquals(file_5_state.pair_state, 'synchronized')
        folder_3_state = self.engine_1.get_dao().get_state_from_local(folder_3_state.local_path)
        self.assertEquals(folder_3_state.pair_state, 'synchronized')

    def test_synchronization_give_up(self):
        # Override error threshold to 1 instead of 3
        test_error_threshold = 1
        self.queue_manager_1._error_threshold = test_error_threshold

        # Bound root but nothing is synchronized yet
        local = self.local_client_1
        self.assertFalse(local.exists('/'))

        # Perform first scan and sync
        self.engine_1.start()
        self.wait_sync(wait_for_async=True)
        self.assertTrue(local.exists('/'))
        self.engine_1.stop()

        # Let's create some documents on the client and the server
        local.make_folder('/', 'Folder 3')
        self.make_server_tree(deep=False)

        # Simulate a server failure on file download
        self.engine_1.remote_filtered_fs_client_factory = RemoteTestClient
        self.engine_1.invalidate_client_cache()
        error = urllib2.HTTPError(None, 500, 'Mock download error', None, None)
        self.engine_1.get_remote_client().make_download_raise(error)

        # File is not synchronized but synchronization does not fail either,
        # errors are handled and queue manager has given up on them
        self.engine_1.start()
        self.wait_sync(wait_for_async=True)
        states_in_error = self.engine_1.get_dao().get_errors(limit=test_error_threshold)
        self.assertEquals(len(states_in_error), 1)
        workspace_children = self.engine_1.get_dao().get_states_from_partial_local('/' + self.workspace_title + '/')
        self.assertEquals(len(workspace_children), 4)
        for state in workspace_children:
            if state.folderish:
                self.assertEquals(state.pair_state, 'synchronized')
            else:
                self.assertNotEqual(state.pair_state, 'synchronized')

        # Remove faulty client and reset errors
        self.engine_1.get_remote_client().make_download_raise(None)
        self.engine_1.remote_filtered_fs_client_factory = RemoteFilteredFileSystemClient
        self.engine_1.invalidate_client_cache()
        for state in states_in_error:
            self.engine_1.get_dao().reset_error(state)

        # Verify that everything now gets synchronized
        self.wait_sync()
        states_in_error = self.engine_1.get_dao().get_errors(limit=test_error_threshold)
        self.assertEquals(len(states_in_error), 0)
        workspace_children = self.engine_1.get_dao().get_states_from_partial_local('/' + self.workspace_title + '/')
        self.assertEquals(len(workspace_children), 4)
        for state in workspace_children:
            self.assertEquals(state.pair_state, 'synchronized')

    def test_synchronization_offline(self):
        # Bound root but nothing is synchronized yet
        local = self.local_client_1
        self.assertFalse(local.exists('/'))

        # Perform first scan and sync
        self.engine_1.start()
        self.wait_sync(wait_for_async=True)
        self.assertTrue(local.exists('/'))
        self.engine_1.stop()

        # Let's create some documents on the client and the server
        local.make_folder('/', 'Folder 3')
        self.make_server_tree(deep=False)

        # Find various ways to simulate a network failure
        self.engine_1.remote_filtered_fs_client_factory = RemoteTestClient
        self.engine_1.invalidate_client_cache()
        errors = [
            urllib2.URLError('Mock URLError'),
            socket.error('Mock socket error'),
            urllib2.HTTPError(None, 503, 'Mock HTTPError', None, None)
        ]
        engine_started = False
        for error in errors:
            self.engine_1.get_remote_client().make_execute_raise(error)
            if not engine_started:
                self.engine_1.start()
                engine_started = True
            # Synchronization doesn't occur but does not fail either.
            # - one '_synchronize_locally_created' error is registered for Folder 3
            # - engine goes offline because of RemoteWatcher._handle_changes
            # - no states are inserted for the remote documents
            self.wait_sync(wait_for_async=True, timeout=5, fail_if_timeout=False)
            states_in_error = self.engine_1.get_dao().get_errors(limit=0)
            self.assertEquals(len(states_in_error), 1)
            self.assertEquals(states_in_error[0].local_name, 'Folder 3')
            self.assertTrue(self.engine_1.is_offline())
            workspace_children = self.engine_1.get_dao().get_states_from_partial_local('/' + self.workspace_title + '/')
            self.assertEquals(len(workspace_children), 1)
            self.assertNotEqual(workspace_children[0].pair_state, 'synchronized')
            self.engine_1.set_offline(value=False)

        # Re-enable network
        self.engine_1.get_remote_client().make_execute_raise(None)
        self.engine_1.remote_filtered_fs_client_factory = RemoteFilteredFileSystemClient
        self.engine_1.invalidate_client_cache()

        # Verify that everything now gets synchronized
        self.wait_sync(wait_for_async=True)
        self.assertFalse(self.engine_1.is_offline())
        states_in_error = self.engine_1.get_dao().get_errors(limit=0)
        self.assertEquals(len(states_in_error), 0)
        workspace_children = self.engine_1.get_dao().get_states_from_partial_local('/' + self.workspace_title + '/')
        self.assertEquals(len(workspace_children), 4)
        for state in workspace_children:
            self.assertEqual(state.pair_state, 'synchronized')

    def test_conflict_detection(self):
        # Fetch the workspace sync root
        local = self.local_client_1
        self.engine_1.start()
        self.wait_sync(wait_for_async=True)
        self.assertTrue(local.exists('/'))

        # Let's create a file on the client and synchronize it.
        local_path = local.make_file('/', 'Some File.doc', content="Original content.")
        self.wait_sync()

        # Let's modify it concurrently but with the same content (digest)
        self.engine_1.suspend()
        time.sleep(OS_STAT_MTIME_RESOLUTION)
        local.update_content(local_path, 'Same new content.')

        remote_2 = self.remote_document_client_2
        remote_2.update_content('/Some File.doc', 'Same new content.')
        self.engine_1.resume()

        # Let's synchronize and check the conflict handling: automatic
        # resolution will work for this case
        self.wait_sync(wait_for_async=True)
        self.assertEquals(len(self.engine_1.get_conflicts()), 0)
        workspace_children = self.engine_1.get_dao().get_states_from_partial_local('/' + self.workspace_title + '/')
        self.assertEquals(len(workspace_children), 1)
        self.assertEquals(workspace_children[0].pair_state, 'synchronized')

        local_children = local.get_children_info('/')
        self.assertEquals(len(local_children), 1)
        self.assertEquals(local_children[0].name, 'Some File.doc')
        self.assertEquals(local.get_content(local_path), 'Same new content.')
        remote_1 = self.remote_document_client_1
        remote_children = remote_1.get_children_info(self.workspace)
        self.assertEquals(len(remote_children), 1)
        self.assertEquals(remote_children[0].filename, 'Some File.doc')
        self.assertEquals(remote_1.get_content('/Some File.doc'), 'Same new content.')

        # Let's trigger another conflict that cannot be resolved
        # automatically:
        self.engine_1.suspend()
        time.sleep(OS_STAT_MTIME_RESOLUTION)
        local.update_content(local_path, 'Local new content.')

        remote_2.update_content('/Some File.doc', 'Remote new content.')
        self.engine_1.resume()

        # Let's synchronize and check the conflict handling
        self.wait_sync(wait_for_async=True)
        self.assertEquals(len(self.engine_1.get_conflicts()), 1)
        workspace_children = self.engine_1.get_dao().get_states_from_partial_local('/' + self.workspace_title + '/')
        self.assertEquals(len(workspace_children), 1)
        self.assertEquals(workspace_children[0].pair_state, 'conflicted')

        local_children = local.get_children_info('/')
        self.assertEquals(len(local_children), 1)
        self.assertEquals(local_children[0].name, 'Some File.doc')
        self.assertEquals(local.get_content(local_path), 'Local new content.')
        remote_children = remote_1.get_children_info(self.workspace)
        self.assertEquals(len(remote_children), 1)
        self.assertEquals(remote_children[0].filename, 'Some File.doc')
        self.assertEquals(remote_1.get_content('/Some File.doc'), 'Remote new content.')

    def test_synchronize_deep_folders(self):
        # Increase Automation execution timeout for NuxeoDrive.GetChangeSummary
        # because of the recursive parent FileSystemItem adaptation
        self.engine_1.timeout = 60
        self.engine_1.start()

        # Create a file deep down in the hierarchy
        remote = self.remote_document_client_1

        folder_name = '0123456789'
        folder_depth = 40
        folder = '/'
        for _ in range(folder_depth):
            folder = remote.make_folder(folder, folder_name)

        remote.make_file(folder, "File.odt", content="Fake non-zero content.")

        self.wait_sync(wait_for_async=True)

        local = self.local_client_1
        expected_folder_path = ('/' + folder_name) * folder_depth

        expected_file_path = expected_folder_path + '/File.odt'
        self.assertTrue(local.exists(expected_folder_path))
        self.assertTrue(local.exists(expected_file_path))
        self.assertEquals(local.get_content(expected_file_path),
                          "Fake non-zero content.")

        # Delete the nested folder structure on the remote server
        # and synchronize again
        remote.delete('/' + folder_name)

        self.wait_sync(wait_for_async=True)

        self.assertFalse(local.exists(expected_folder_path))
        self.assertFalse(local.exists(expected_file_path))

    def test_create_content_in_readonly_area(self):
        self.engine_1.start()

        # Let's create a subfolder of the main readonly folder
        local = LocalClient(self.local_nxdrive_folder_1)
        local.make_folder('/', 'Folder 3')
        local.make_file('/Folder 3', 'File 1.txt', content='Some content.')
        local.make_folder('/Folder 3', 'Sub Folder 1')
        local.make_file('/Folder 3/Sub Folder 1', 'File 2.txt', content='Some other content.')
        self.wait_sync(wait_for_async=True)

        # States have been created for the subfolder and its content,
        # subfolder is marked as unsynchronized
        states = self.engine_1.get_dao().get_states_from_partial_local('/')
        self.assertEquals(len(states), 6)
        sorted_states = sorted(states, key=lambda x: x.local_path)
        self.assertEquals(sorted_states[0].local_name, '')
        self.assertEquals(sorted_states[0].pair_state, 'synchronized')
        self.assertEquals(sorted_states[1].local_name, 'Folder 3')
        self.assertEquals(sorted_states[1].pair_state, 'unsynchronized')
        self.assertEquals(sorted_states[2].local_name, 'File 1.txt')
        self.assertEquals(sorted_states[2].pair_state, 'locally_created')
        self.assertEquals(sorted_states[3].local_name, 'Sub Folder 1')
        self.assertEquals(sorted_states[3].pair_state, 'locally_created')
        self.assertEquals(sorted_states[4].local_name, 'File 2.txt')
        self.assertEquals(sorted_states[4].pair_state, 'locally_created')
        self.assertEquals(sorted_states[5].local_name, self.workspace_title)
        self.assertEquals(sorted_states[5].pair_state, 'synchronized')

        # Let's create a file in the main readonly folder
        local.make_file('/', 'A file in a readonly folder.txt', content='Some Content')
        self.wait_sync()

        # A state has been created, marked as unsynchronized
        # Other states are unchanged
        states = self.engine_1.get_dao().get_states_from_partial_local('/')
        self.assertEquals(len(states), 7)
        sorted_states = sorted(states, key=lambda x: x.local_path)
        self.assertEquals(sorted_states[0].local_name, '')
        self.assertEquals(sorted_states[0].pair_state, 'synchronized')
        self.assertEquals(sorted_states[1].local_name, 'A file in a readonly folder.txt')
        self.assertEquals(sorted_states[1].pair_state, 'unsynchronized')
        self.assertEquals(sorted_states[2].local_name, 'Folder 3')
        self.assertEquals(sorted_states[2].pair_state, 'unsynchronized')
        self.assertEquals(sorted_states[3].local_name, 'File 1.txt')
        self.assertEquals(sorted_states[3].pair_state, 'locally_created')
        self.assertEquals(sorted_states[4].local_name, 'Sub Folder 1')
        self.assertEquals(sorted_states[4].pair_state, 'locally_created')
        self.assertEquals(sorted_states[5].local_name, 'File 2.txt')
        self.assertEquals(sorted_states[5].pair_state, 'locally_created')
        self.assertEquals(sorted_states[6].local_name, self.workspace_title)
        self.assertEquals(sorted_states[6].pair_state, 'synchronized')

        # Let's create a file and a folder in a folder on which the Write
        # permission has been removed. Thanks to NXP-13119, this permission
        # change will be detected server-side, thus fetched by the client
        # in the remote change summary, and the remote_can_create_child flag
        # on which the synchronizer relies to check if creation is allowed
        # will be set to False and no attempt to create the remote file
        # will be made.
        # States will be marked as unsynchronized.

        # Create local folder and synchronize it remotely
        local = self.local_client_1
        local.make_folder(u'/', u'Readonly folder')
        self.wait_sync()

        remote = self.remote_document_client_1
        self.assertTrue(remote.exists(u'/Readonly folder'))

        # Check remote_can_create_child flag in pair state
        readonly_folder_state = self.engine_1.get_dao().get_state_from_local('/' + self.workspace_title
                                                                             + '/Readonly folder')
        self.assertTrue(readonly_folder_state.remote_can_create_child)

        # Wait again for synchronization to detect remote folder creation triggered
        # by last synchronization and make sure we get a clean state at
        # next change summary
        self.wait_sync(wait_for_async=True)
        readonly_folder_state = self.engine_1.get_dao().get_state_from_local('/' + self.workspace_title
                                                                             + '/Readonly folder')
        self.assertTrue(readonly_folder_state.remote_can_create_child)

        # Set remote folder as readonly for test user
        readonly_folder_path = TEST_WORKSPACE_PATH + u'/Readonly folder'
        op_input = "doc:" + readonly_folder_path
        self.root_remote_client.execute("Document.SetACE", op_input=op_input, user="nuxeoDriveTestUser_user_1",
                                        permission="Read")
        self.root_remote_client.block_inheritance(readonly_folder_path, overwrite=False)

        # Wait to make sure permission change is detected.
        self.wait_sync(wait_for_async=True)
        # Re-fetch folder state and check remote_can_create_child flag has been updated
        readonly_folder_state = self.engine_1.get_dao().get_state_from_local('/' + self.workspace_title
                                                                             + '/Readonly folder')
        self.assertFalse(readonly_folder_state.remote_can_create_child)

        # Try to create a local file and folder in the readonly folder,
        # they should not be created remotely and be marked as unsynchronized.
        local.make_file(u'/Readonly folder', u'File in readonly folder', u"File content")
        local.make_folder(u'/Readonly folder', u'Folder in readonly folder')
        self.wait_sync()
        self.assertFalse(remote.exists(u'/Readonly folder/File in readonly folder'))
        self.assertFalse(remote.exists(u'/Readonly folder/Folder in readonly folder'))

        states = self.engine_1.get_dao().get_states_from_partial_local('/' + self.workspace_title + '/Readonly folder')
        self.assertEquals(len(states), 3)
        sorted_states = sorted(states, key=lambda x: x.local_path)
        self.assertEquals(sorted_states[0].local_name, 'Readonly folder')
        self.assertEquals(sorted_states[0].pair_state, 'synchronized')
        self.assertEquals(sorted_states[1].local_name, 'File in readonly folder')
        self.assertEquals(sorted_states[1].pair_state, 'unsynchronized')
        self.assertEquals(sorted_states[2].local_name, 'Folder in readonly folder')
        self.assertEquals(sorted_states[2].pair_state, 'unsynchronized')

    def test_synchronize_special_filenames(self):
        local = self.local_client_1
        remote = self.remote_document_client_1
        self.engine_1.start()

        # Create a remote folder with a weird name
        folder = remote.make_folder(self.workspace, u'Folder with forbidden chars: / \\ * < > ? "')

        self.wait_sync(wait_for_async=True)
        folder_names = [i.name for i in local.get_children_info('/')]
        self.assertEquals(folder_names, [u'Folder with forbidden chars- - - - - - - -'])

        # Create a remote file with a weird name
        remote.make_file(folder, u'File with forbidden chars: / \\ * < > ? ".doc', content="some content")

        self.wait_sync(wait_for_async=True)
        file_names = [i.name for i in local.get_children_info(local.get_children_info('/')[0].path)]
        self.assertEquals(file_names, [u'File with forbidden chars- - - - - - - -.doc'])

    def test_synchronize_deleted_blob(self):
        local = self.local_client_1
        remote = self.remote_document_client_1
        self.engine_1.start()

        # Create a doc with a blob in the remote root workspace
        # then synchronize
        remote.make_file('/', 'test.odt', 'Some content.')

        self.wait_sync(wait_for_async=True)
        self.assertTrue(local.exists('/test.odt'))

        # Delete the blob from the remote doc then synchronize
        remote.delete_content('/test.odt')

        self.wait_sync(wait_for_async=True)
        self.assertFalse(local.exists('/test.odt'))

    def test_synchronize_deletion(self):
        local = self.local_client_1
        remote = self.remote_document_client_1
        self.engine_1.start()

        # Create a remote folder with 2 children then synchronize
        remote.make_folder('/', 'Remote folder',)
        remote.make_file('/Remote folder', 'Remote file 1.odt', 'Some content.')
        remote.make_file('/Remote folder', 'Remote file 2.odt', 'Other content.')

        self.wait_sync(wait_for_async=True)
        self.assertTrue(local.exists('/Remote folder'))
        self.assertTrue(local.exists('/Remote folder/Remote file 1.odt'))
        self.assertTrue(local.exists('/Remote folder/Remote file 2.odt'))

        # Delete remote folder then synchronize
        remote.delete('/Remote folder')

        self.wait_sync(wait_for_async=True)
        self.assertFalse(local.exists('/Remote folder'))
        self.assertFalse(local.exists('/Remote folder/Remote file 1.odt'))
        self.assertFalse(local.exists('/Remote folder/Remote file 2.odt'))

        # Create a local folder with 2 children then synchronize
        local.make_folder('/', 'Local folder')
        local.make_file('/Local folder', 'Local file 1.odt', 'Some content.')
        local.make_file('/Local folder', 'Local file 2.odt', 'Other content.')

        self.wait_sync()
        self.assertTrue(remote.exists('/Local folder'))
        self.assertTrue(remote.exists('/Local folder/Local file 1.odt'))
        self.assertTrue(remote.exists('/Local folder/Local file 2.odt'))

        # Delete local folder then synchronize
        time.sleep(OS_STAT_MTIME_RESOLUTION)
        local.delete('/Local folder')

        self.wait_sync()
        self.assertFalse(remote.exists('/Local folder'))
        # Wait for async completion as recursive deletion of children is done
        # by the BulkLifeCycleChangeListener which is asynchronous
        self.wait()
        self.assertFalse(remote.exists('/Local folder/Local file 1.odt'))
        self.assertFalse(remote.exists('/Local folder/Local file 2.odt'))
