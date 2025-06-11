# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]
### Added
- Support for Jolt V2.1, which uses a different voltage "safe range".

## [1.3.0] - 2025-06-11
### Added
- Differentiation between Jolt V1 and V2
- Front-end offset calibration algorithm.
- UI for starting and stopping front-end offset calibration.
- Automatic loading of front-end offset calibration file when present.
- Usage of the best front-end offset from calibration file when settings change.
- Controls for manual front-end offset and output voltage.

### Changed
- Improved startup behavior by fixing an EOT character bug in serial communication.
- Refined operating voltage control: the input field and current value are now separate elements for better usability.
- The hardware's operating voltage is now more accurate due to iterative voltage setting logic in the driver.
- Text input fields are easier to use, with better handling of event properties.

## [1.2.0] - 2023-07-24
### Added
- Support for changing the front-end voltage via config file.

### Changed
- Expanded README documentation with more details.

## [1.1.1] - 2022-02-17
### Added
- Support for panchromatic JOLT via special `.INI` option `SIGNAL/rgb_filter`.
- Auto BC button (for firmware without built-in support).

### Fixed
- Firmware updater no longer fails to start on Linux.

## [1.1.0] - 2021-07-20
### Added
- Support for both single-ended and differential personality boards via `.INI` option.

### Compatibility
- Executables work on both Windows 7 and Windows 10.

## [1.0.4] - 2021-06-14
### Fixed
- Application no longer fails to start if `.ini` file is missing.

### Changed
- Updated release procedure documentation.

## [1.0.3] - 2021-06-01
### Fixed
- Various GUI improvements and bug fixes.

### Changed
- Updated documentation.

## [1.0.1] - 2020-03-17
### Fixed
- Small bug fixes in GUI.

### Added
- Option to erase firmware in the firmware updater.
