import logging
import sys
from argparse import ArgumentParser, RawTextHelpFormatter, SUPPRESS
from itertools import chain
from os import uname
from pathlib import Path
from typing import Any, Dict, List, Set

from src.config.os_type import OSArch, OSConfig, OSType, SUPPORTED_OS_TYPES
from src.error import CriticalError, OldManifestVersion


class Config:
    def __init__(self, argv: List[str]):
        self.dest_crane_symlink: Path = None
        self.dest_dir: Path
        self.dest_files: Path
        self.dest_grafana_dashboards: Path
        self.dest_images: Path
        self.dest_manifest: Path
        self.dest_packages: Path
        self.distro_subdir: Path
        self.is_log_file_enabled: bool
        self.log_file: Path
        self.log_level: int
        self.os_arch: OSArch
        self.os_type: OSType
        self.pyyaml_installed: bool = False
        self.repo_path: Path
        self.repos_backup_file: Path
        self.reqs_path: Path
        self.rerun: bool = False
        self.retries: int
        self.script_path: Path
        self.verbose_mode: bool
        self.was_backup_created: bool = False

        self.__add_args(argv)

        self.__LINE_SIZE: int = 50  # used in printing

        if not self.rerun:
            self.__log_info_summary()

    def __log_info_summary(self):
        """
        Helper function for printing all parsed arguments
        """

        lines: List[str] = ['Info summary:']
        lines.append('-' * self.__LINE_SIZE)

        lines.append(f'OS Arch: {self.os_arch.value}')
        lines.append(f'OS Type: {self.os_type.os_name}')
        lines.append(f'Script location: {str(self.script_path.absolute())}')
        lines.append('Directories used:')
        lines.append(f'- files:              {str(self.dest_files)}')
        lines.append(f'- grafana dashboards: {str(self.dest_grafana_dashboards)}')
        lines.append(f'- images:             {str(self.dest_images)}')
        lines.append(f'- packages:           {str(self.dest_packages)}')
        lines.append(f'Repos backup file: {str(self.repos_backup_file)}')

        if self.dest_manifest:
            lines.append(f'Manifest used: {str(self.dest_manifest.absolute())}')
        else:
            lines.append('Manifest not used, downloading all available requirements...')

        if self.is_log_file_enabled:
            lines.append(f'Log file location: {str(self.log_file.absolute())}')

        lines.append(f'Verbose mode: {self.verbose_mode}')
        lines.append(f'Retries count: {self.retries}')

        lines.append('-' * self.__LINE_SIZE)

        logging.info('\n'.join(lines))

    def __create_parser(self) -> ArgumentParser:
        parser = ArgumentParser(description='Download Requirements', formatter_class=RawTextHelpFormatter)

        # required arguments:
        parser.add_argument('destination_dir', metavar='DEST_DIR', type=Path, action='store', nargs='+',
                            help='requirements will be downloaded to this directory')

        all_oss: List[OSConfig] = list(chain(*SUPPORTED_OS_TYPES.values()))
        supported_os: str = "|".join({os.name for os in all_oss})
        parser.add_argument('os_type', metavar='OS_TYPE', type=str, action='store', nargs='+',
                            help=f'which of the supported OS will be used: ({supported_os}|detect)\n'
                            'when using `detect`, script will try to find out which OS is being used')

        # optional arguments:
        parser.add_argument('--repos-backup-file', metavar='BACKUP_FILE', action='store',
                            dest='repos_backup_file', default='/var/tmp/enabled-system-repos.tar',
                            help='path to a backup file')
        parser.add_argument('--retries-count', '-r', metavar='COUNT', type=int, action='store', dest='retries',
                            default=3, help='how many retries before stopping operation')

        parser.add_argument('--log-file', '-l', metavar='LOG_FILE', type=Path, action='store', dest='log_file',
                            default=Path('./download-requirements.log'),
                            help='logs will be saved to this file')
        parser.add_argument('--log-level', metavar='LOG_LEVEL', type=str, action='store', dest='log_level',
                            default='info', help='set up log level, available levels: (error|warn|info|debug)')
        parser.add_argument('--no-logfile', action='store_true', dest='no_logfile',
                            help='no logfile will be created')

        parser.add_argument('--verbose', '-v',  action='store_true', dest='verbose',
                            help='more verbose output will be provided')

        parser.add_argument('--manifest', '-m', metavar='MANIFEST_PATH', type=Path, action='store', dest='manifest',
                            help='manifest file generated by epicli')

        # offline mode rerun options:
        parser.add_argument('--rerun', action='store_true', dest='rerun',
                            default=False, help=SUPPRESS)
        parser.add_argument('--pyyaml-installed', action='store_true', dest='pyyaml_installed',
                            default=False, help=SUPPRESS)

        return parser

    def __get_matching_os_type(self, arch: OSArch, os_type: str) -> OSType:
        """
        Check if the parsed OS type fits supported distributons.

        :param os_type: distro type to be checked
        :raise: on failure - CriticalError
        """

        for ost in SUPPORTED_OS_TYPES[arch]:
            if (os_type.upper() in ost.os_name.upper() or
                os_type.upper() in [alias.upper() for alias in ost.os_aliases]):
                logging.debug(f'Found Matching OS: `{ost.name}`')
                return ost

        raise CriticalError('Could not detect OS type')

    def __detect_os_type(self, arch: OSArch) -> OSType:
        """
        On most modern GNU/Linux OSs info about current distribution
        can be found at /etc/os-release.
        Check this file to find out on which distro this script is ran.
        """

        os_release = Path('/etc/os-release')

        if os_release.exists():
            with open(os_release) as os_release_handler:
                for line in os_release_handler.readlines():
                    if 'ID' in line:
                        return self.__get_matching_os_type(arch, line.split('=')[1].replace('"', '').strip())

        raise CriticalError('Could not detect OS type')

    def __setup_logger(self, log_level: str, log_file: Path, no_logfile: bool):

        # setup the logger:
        log_levels = {
            # map input log level to Python's logging library
            'error': logging.ERROR,
            'warn': logging.WARNING,
            'info': logging.INFO,
            'debug': logging.DEBUG
        }
        self.log_level = log_levels[log_level.lower()]

        log_format = '%(asctime)s [%(levelname)s]: %(message)s'

        # add stdout logger:
        logging.basicConfig(stream=sys.stdout, level=self.log_level,
                            format=log_format)

        # add log file:
        if not no_logfile:
            root_logger = logging.getLogger()
            file_handler = logging.FileHandler(log_file)
            file_handler.setLevel(self.log_level)
            file_handler.setFormatter(logging.Formatter(fmt=log_format))
            root_logger.addHandler(file_handler)

    def __add_args(self, argv: List[str]):
        """
        Run the parser and add all of the arguments to the Config object.

        :param argv: input arguments to be parsed
        """

        self.script_path = Path(argv[0]).absolute().parents[0]
        self.repo_path = self.script_path / 'repositories'
        self.reqs_path = self.script_path / 'requirements'

        args = self.__create_parser().parse_args(argv[1:]).__dict__

        self.log_file = args['log_file']
        self.__setup_logger(args['log_level'], self.log_file, args['no_logfile'])

        # add required arguments:
        self.os_arch = OSArch(uname().machine)
        if args['os_type'][0] == 'detect':
            self.os_type = self.__detect_os_type(self.os_arch)
        else:
            self.os_type = self.__get_matching_os_type(self.os_arch, args['os_type'][0])

        self.dest_dir = args['destination_dir'][0].absolute()
        self.dest_grafana_dashboards = self.dest_dir / 'grafana_dashboards'
        self.dest_files = self.dest_dir / 'files'
        self.dest_images = self.dest_dir / 'images'
        self.dest_packages = self.dest_dir / 'packages'

        self.family_subdir = Path(f'{self.os_arch.value}/{self.os_type.os_family.value}')
        self.distro_subdir = self.family_subdir / self.os_type.os_name

        # add optional arguments
        self.dest_manifest = args['manifest'] or None
        self.is_log_file_enabled = False if args['no_logfile'] else True
        self.repos_backup_file = Path(args['repos_backup_file'])
        self.retries = args['retries']
        self.verbose_mode = True if self.log_level == logging.DEBUG else args['verbose']

        # offline mode
        self.rerun = args['rerun']
        self.pyyaml_installed = args['pyyaml_installed']

    def __get_parsed_manifest_data_output(self, manifest: Dict[str, Any]) -> str:
        lines: List[str] = ['Manifest summary:']

        lines.append('-' * self.__LINE_SIZE)

        lines.append('Components requested:')
        for component in manifest['requested-components']:
            lines.append(f'- {component}')

        lines.append('')

        lines.append('Features requested:')
        for feature in manifest['requested-features']:
            lines.append(f'- {feature}')

        return '\n'.join(lines)

    def __get_requirements_output(self, requirements: Dict[str, Any]) -> str:
        lines: List[str] = []

        for reqs in (('files', 'Files'),
                     ('grafana-dashboards', 'Dashboards')):
            reqs_to_download = sorted(requirements[reqs[0]])
            if reqs_to_download:
                lines.append('')
                lines.append(f'{reqs[1]} to download:')
                for req_to_download in reqs_to_download:
                    lines.append(f'- {req_to_download}')

        images = requirements['images']
        images_to_print: List[str] = []
        for image_category in images:
            for image in images[image_category]:
                images_to_print.append(image)

        if images_to_print:
            lines.append('')
            lines.append('Images to download:')
            for image in sorted(set(images_to_print)):
                lines.append(f'- {image}')

        lines.append('')

        return '\n'.join(lines)

    def __filter_files(self, requirements: Dict[str, Any],
                             manifest: Dict[str, Any]):
        """
        See :func:`~config.Config.__filter_manifest`
        """
        files = requirements['files']
        files_to_exclude: List[str] = []
        for file in files:
            deps = files[file]['deps']
            if all(dep not in manifest['requested-features'] for dep in deps) and deps != 'default':
                files_to_exclude.append(file)

        if files_to_exclude:
            requirements['files'] = {url: data for url, data in files.items() if url not in files_to_exclude}

    def __filter_images(self, requirements: Dict[str, Any], manifest: Dict[str, Any]):
        """
        See :func:`~config.Config.__filter_manifest`
        """
        # prepare image groups:
        images = requirements['images']
        images_to_download: Dict[str, Dict] = {}
        selected_images: Set[str] = set()
        for image_group in images:
            images_to_download[image_group] = {}

        for image_group in images:
            if image_group in manifest['requested-features']:
                for image, data in images[image_group].items():
                    if image not in selected_images:
                        images_to_download[image_group][image] = data
                        selected_images.add(image)

        if images_to_download:
            requirements['images'] = images_to_download

    def __filter_manifest(self, requirements: Dict[str, Any],
                                manifest: Dict[str, Any]):
        """
        Filter entries in the `requirements` based on the parsed `manifest` documents.

        :param requirements: parsed requirements which will be filtered based on the `manifest` content
        :param manifest: parsed documents which will be used to filter `requirements`
        """
        if 'grafana' not in manifest['requested-features']:
            requirements['grafana-dashboards'] = []

        self.__filter_files(requirements, manifest)
        self.__filter_images(requirements, manifest)

    def read_manifest(self, requirements: Dict[str, Any]):
        """
        Construct ManifestReader and parse only required data.
        Not needed entries will be removed from the `requirements`

        :param requirements: parsed requirements which will be filtered based on the manifest output
        """
        if not self.dest_manifest:
            logging.info(self.__get_requirements_output(requirements))
            return

        # Needs to be imported here as the libyaml might be missing on the OS,
        # this could cause crash on config.py import.
        from src.config.manifest_reader import ManifestReader

        mreader = ManifestReader(self.dest_manifest)
        try:
            manifest = mreader.parse_manifest()
            self.__filter_manifest(requirements, manifest)

            if self.verbose_mode:
                logging.info(f'{self.__get_parsed_manifest_data_output(manifest)}\n'
                             f'{self.__get_requirements_output(requirements)}'
                             f'{"-" * self.__LINE_SIZE}')
        except OldManifestVersion:
            pass  # old manifest used, cannot optimize download time