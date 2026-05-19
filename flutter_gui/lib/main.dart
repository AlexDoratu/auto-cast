import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';

void main() {
  runApp(const AutoCastApp());
}

class AutoCastApp extends StatelessWidget {
  const AutoCastApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Auto-Cast',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.dark,
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xff4cc9f0),
          brightness: Brightness.dark,
          surface: const Color(0xff111827),
        ),
        scaffoldBackgroundColor: const Color(0xff0b1020),
        useMaterial3: true,
      ),
      home: const AutoCastHome(),
    );
  }
}

class AutoCastBridge {
  Process? _process;
  int _nextId = 1;
  final _pending = <int, Completer<Map<String, dynamic>>>{};
  void Function(String event, Map<String, dynamic> payload)? onEvent;
  final status = ValueNotifier<String>('Bridge idle');

  Future<void> start() async {
    if (_process != null) {
      return;
    }
    final bridgePath = await _findBridgePath();
    _process = await Process.start(
      await _pythonExecutable(bridgePath),
      _bridgeArguments(bridgePath),
      environment: {
        'PYTHONIOENCODING': 'utf-8',
        'PYTHONUTF8': '1',
      },
      runInShell: true,
      workingDirectory: File(bridgePath).parent.path,
    );
    _process!.stdout
        .transform(const Utf8Decoder(allowMalformed: true))
        .transform(const LineSplitter())
        .listen(_handleLine, onError: _failAll);
    _process!.stderr
        .transform(const Utf8Decoder(allowMalformed: true))
        .listen((line) {
      final trimmed = line.trim();
      if (trimmed.isNotEmpty) {
        status.value = trimmed;
      }
    });
    _process!.exitCode.then((code) {
      _process = null;
      _failAll('Bridge exited with code $code');
    });
    status.value = 'Bridge ready';
  }

  Future<String> _findBridgePath() async {
    final roots = <Directory>[
      Directory.current,
      File(Platform.resolvedExecutable).parent,
    ];
    for (final root in roots) {
      var cursor = root;
      for (var depth = 0; depth < 8; depth++) {
        for (final filename in [
          'gui_bridge.exe',
          'auto-cast-bridge.exe',
          'gui_bridge.py'
        ]) {
          final candidate =
              File('${cursor.path}${Platform.pathSeparator}$filename');
          if (await candidate.exists()) {
            return candidate.path;
          }
        }
        final parent = cursor.parent;
        if (parent.path == cursor.path) {
          break;
        }
        cursor = parent;
      }
    }
    throw StateError('gui_bridge.py not found');
  }

  Future<String> _pythonExecutable(String bridgePath) async {
    if (bridgePath.toLowerCase().endsWith('.exe')) {
      return bridgePath;
    }
    final bundled = 'python${Platform.pathSeparator}python.exe';
    final exeDir = File(Platform.resolvedExecutable).parent;
    final bundledPython =
        File('${exeDir.path}${Platform.pathSeparator}$bundled');
    if (await bundledPython.exists()) {
      return bundledPython.path;
    }
    return 'python';
  }

  List<String> _bridgeArguments(String bridgePath) {
    if (bridgePath.toLowerCase().endsWith('.exe')) {
      return ['--stdio'];
    }
    return [bridgePath, '--stdio'];
  }

  Future<Map<String, dynamic>> send(
      String command, Map<String, dynamic> body) async {
    await start();
    final process = _process;
    if (process == null) {
      throw StateError('Bridge is not running');
    }
    final id = _nextId++;
    final completer = Completer<Map<String, dynamic>>();
    _pending[id] = completer;
    process.stdin.writeln(jsonEncode({'id': id, 'command': command, ...body}));
    return completer.future.timeout(const Duration(minutes: 2), onTimeout: () {
      _pending.remove(id);
      throw TimeoutException('Command timed out: $command');
    });
  }

  void _handleLine(String line) {
    final Map<String, dynamic> decoded;
    try {
      decoded = (jsonDecode(line) as Map).cast<String, dynamic>();
    } catch (_) {
      final trimmed = line.trim();
      if (trimmed.isNotEmpty) {
        status.value = trimmed;
      }
      return;
    }
    final event = decoded['event']?.toString();
    if (event != null) {
      onEvent?.call(
          event, (decoded['payload'] as Map? ?? {}).cast<String, dynamic>());
      return;
    }
    final id = decoded['id'] as int?;
    final completer = id == null ? null : _pending.remove(id);
    if (completer == null) {
      return;
    }
    if (decoded['ok'] == true) {
      completer.complete((decoded['result'] as Map).cast<String, dynamic>());
    } else {
      completer.completeError(
          Exception(decoded['error'] ?? 'Bridge command failed'));
    }
  }

  @visibleForTesting
  void handleLineForTest(String line) => _handleLine(line);

  void _failAll(Object error) {
    for (final completer in _pending.values) {
      if (!completer.isCompleted) {
        completer.completeError(error);
      }
    }
    _pending.clear();
  }

  void dispose() {
    _process?.kill();
    _process = null;
    status.dispose();
  }
}

class CastDevice {
  CastDevice(this.data);

  final Map<String, dynamic> data;

  String get name => data['name']?.toString() ?? 'Unknown';
  String get type =>
      data['display_type']?.toString() ?? data['device_type']?.toString() ?? '';
  String get ip => data['ip']?.toString() ?? '';
  String get model => data['model']?.toString() ?? '';
  List<String> get capabilities =>
      (data['capabilities'] as List?)
          ?.map((item) => item.toString())
          .toList() ??
      const [];
  String get subtitle {
    final details = <String>[type, ip];
    if (model.isNotEmpty) {
      details.add(model);
    }
    if (capabilities.length > 1) {
      details.add('prefers DLNA');
    }
    return details.where((item) => item.isNotEmpty).join('  ');
  }
}

class StatusSample {
  StatusSample({
    required this.time,
    required this.score,
    required this.progress,
    required this.positionSeconds,
    required this.latencyMs,
    required this.state,
  });

  final DateTime time;
  final double score;
  final double progress;
  final double positionSeconds;
  final double latencyMs;
  final String state;

  factory StatusSample.fromStatus(Map<String, dynamic> status) {
    final state = status['state']?.toString() ?? 'UNKNOWN';
    final position = (status['position_seconds'] as num?)?.toDouble() ?? 0;
    final duration = (status['duration_seconds'] as num?)?.toDouble() ?? 0;
    final progress = duration > 0 ? (position / duration).clamp(0.0, 1.0) : 0.0;
    return StatusSample(
      time: DateTime.now(),
      score: _stateScore(state, status['playing'] == true),
      progress: progress,
      positionSeconds: position,
      latencyMs: (status['latency_ms'] as num?)?.toDouble() ?? 0,
      state: state,
    );
  }

  static double _stateScore(String state, bool playing) {
    if (state == 'ERROR') {
      return 0.0;
    }
    if (state == 'STOPPED' || state == 'NO_MEDIA_PRESENT' || state == 'IDLE') {
      return 0.25;
    }
    if (state == 'PAUSED_PLAYBACK') {
      return 0.55;
    }
    if (state == 'PLAYING' || playing) {
      return 1.0;
    }
    return 0.4;
  }
}

enum CastMode {
  media('Local File', Icons.video_file),
  video('Video URL', Icons.ondemand_video),
  live('Live URL', Icons.live_tv),
  capture('Capture', Icons.screenshot_monitor);

  const CastMode(this.label, this.icon);

  final String label;
  final IconData icon;
}

enum QueueItemKind { media, video }

class PlaybackQueueItem {
  PlaybackQueueItem({
    required this.kind,
    required this.source,
    required this.title,
    this.startSeconds = 0,
    this.endSeconds,
    this.cachedPath,
    this.cachedMeta,
  });

  final QueueItemKind kind;
  final String source;
  final String title;
  final int startSeconds;
  final int? endSeconds;
  final String? cachedPath;
  final Map<String, dynamic>? cachedMeta;

  bool get isReady => kind == QueueItemKind.media || cachedPath != null;

  PlaybackQueueItem copyWith({
    int? startSeconds,
    int? endSeconds,
    String? cachedPath,
    Map<String, dynamic>? cachedMeta,
    String? title,
  }) {
    return PlaybackQueueItem(
      kind: kind,
      source: source,
      title: title ?? this.title,
      startSeconds: startSeconds ?? this.startSeconds,
      endSeconds: endSeconds ?? this.endSeconds,
      cachedPath: cachedPath ?? this.cachedPath,
      cachedMeta: cachedMeta ?? this.cachedMeta,
    );
  }
}

class TimeRange {
  const TimeRange({required this.startSeconds, required this.endSeconds});

  final int startSeconds;
  final int? endSeconds;
}

class AutoCastHome extends StatefulWidget {
  const AutoCastHome({super.key});

  @override
  State<AutoCastHome> createState() => _AutoCastHomeState();
}

class _AutoCastHomeState extends State<AutoCastHome> {
  final bridge = AutoCastBridge();
  final liveController = TextEditingController();
  final videoController = TextEditingController();
  final mediaStartController = TextEditingController();
  final mediaEndController = TextEditingController();
  final videoStartController = TextEditingController();
  final videoEndController = TextEditingController();
  final devices = <CastDevice>[];
  final windows = <Map<String, dynamic>>[];
  final monitors = <Map<String, dynamic>>[];
  CastDevice? selectedDevice;
  String? selectedFile;
  int? selectedWindowIndex;
  int selectedMonitorIndex = 0;
  CastMode selectedMode = CastMode.media;
  bool busy = false;
  String status = 'Ready';
  double volume = 70;
  double bitrate = 3500;
  double fps = 10;
  Timer? statusTimer;
  Timer? autoSearchTimer;
  Map<String, dynamic> playbackStatus = const {
    'playing': false,
    'state': 'IDLE',
    'status': 'No active playback',
    'position_seconds': 0,
    'duration_seconds': 0,
    'volume': null,
  };
  final statusSamples = <StatusSample>[];
  Map<String, dynamic>? inspectedVideo;
  Map<String, dynamic>? cachedVideo;
  Map<String, dynamic>? downloadProgress;
  String cacheDir = '';
  String? activeDownloadTaskId;
  int? activeDownloadQueueIndex;
  String? activeDownloadSourceUrl;
  bool playAfterDownload = false;
  bool seeking = false;
  bool pollingStatus = false;
  bool autoSearchResume = false;
  bool autoResumeBusy = false;
  bool queueActive = false;
  bool queueAdvancing = false;
  int currentQueueIndex = -1;
  final playbackQueue = <PlaybackQueueItem>[];
  Timer? bitrateDebounce;

  @override
  void initState() {
    super.initState();
    bridge.onEvent = _handleBridgeEvent;
    unawaited(_refreshSources());
    unawaited(_refreshState());
    statusTimer = Timer.periodic(
        const Duration(seconds: 2), (_) => unawaited(_pollPlaybackStatus()));
  }

  @override
  void dispose() {
    statusTimer?.cancel();
    autoSearchTimer?.cancel();
    bitrateDebounce?.cancel();
    bridge.dispose();
    liveController.dispose();
    videoController.dispose();
    mediaStartController.dispose();
    mediaEndController.dispose();
    videoStartController.dispose();
    videoEndController.dispose();
    super.dispose();
  }

  Future<void> _run(String label, Future<void> Function() action) async {
    setState(() {
      busy = true;
      status = label;
    });
    try {
      await action();
    } catch (error) {
      setState(() => status = error.toString());
    } finally {
      if (mounted) {
        setState(() => busy = false);
      }
    }
  }

  Future<void> _scan() async {
    await _run('Scanning devices...', () async {
      final result = await bridge.send('scan', {'timeout': 5.0});
      final items = (result['devices'] as List? ?? [])
          .map((item) => CastDevice((item as Map).cast<String, dynamic>()))
          .toList();
      setState(() {
        devices
          ..clear()
          ..addAll(items);
        selectedDevice = devices.isEmpty ? null : devices.first;
        status = 'Found ${devices.length} device(s)';
      });
    });
  }

  void _setAutoSearchResume(bool enabled) {
    setState(() => autoSearchResume = enabled);
    autoSearchTimer?.cancel();
    if (!enabled) {
      return;
    }
    status = 'Auto Search & Resume enabled';
    unawaited(_tryAutoResume());
    autoSearchTimer = Timer.periodic(
        const Duration(seconds: 5), (_) => unawaited(_tryAutoResume()));
  }

  Future<void> _tryAutoResume() async {
    if (!autoSearchResume ||
        autoResumeBusy ||
        playbackStatus['playing'] == true) {
      return;
    }
    autoResumeBusy = true;
    try {
      final result = await bridge.send('resume_last', {'timeout': 4.0});
      if (!mounted) {
        return;
      }
      final resultStatus = result['status']?.toString() ?? '';
      setState(() {
        if (resultStatus == 'searching') {
          status = 'Searching for last TV...';
        } else if (resultStatus == 'skipped') {
          status = result['reason']?.toString() ?? 'No resumable state';
        } else {
          status = 'Resumed last cast';
        }
      });
      unawaited(_pollPlaybackStatus());
    } catch (error) {
      if (mounted) {
        setState(() => status = error.toString());
      }
    } finally {
      autoResumeBusy = false;
    }
  }

  void _handleBridgeEvent(String event, Map<String, dynamic> payload) {
    if (!mounted) {
      return;
    }
    if (event == 'download_progress') {
      setState(() {
        downloadProgress = payload;
        final percent = (payload['percent'] as num?)?.toDouble();
        final phase = payload['phase']?.toString() ?? 'Downloading video';
        status = percent == null ? phase : '$phase ${_formatPercent(percent)}';
      });
    } else if (event == 'download_complete') {
      final taskId = payload['task_id']?.toString();
      final completedQueueIndex = activeDownloadQueueIndex;
      final payloadSource = _nonEmptyString(payload['source_url']);
      if (payloadSource != null &&
          activeDownloadSourceUrl != null &&
          payloadSource != activeDownloadSourceUrl) {
        return;
      }
      final expectedDirectDownload = playAfterDownload &&
          (taskId == null ||
              activeDownloadTaskId == null ||
              taskId == activeDownloadTaskId);
      final expectedQueueDownload = completedQueueIndex != null &&
          (taskId == null ||
              activeDownloadTaskId == null ||
              taskId == activeDownloadTaskId);
      if (taskId != null && !expectedDirectDownload && !expectedQueueDownload) {
        return;
      }
      final completedSource =
          _nonEmptyString(payload['source_url']) ?? activeDownloadSourceUrl;
      final completedPayload = {
        ...payload,
        if (completedSource != null) 'source_url': completedSource,
      };
      final shouldPlayAfterDownload = playAfterDownload;
      final queueIndexToPlay = queueIndexToPlayAfterDownloadForTest(
        queueActive: queueActive,
        queueAdvancing: queueAdvancing,
        currentQueueIndex: currentQueueIndex,
        completedQueueIndex: completedQueueIndex,
      );
      setState(() {
        if (completedQueueIndex != null &&
            completedQueueIndex >= 0 &&
            completedQueueIndex < playbackQueue.length) {
          final index = completedQueueIndex;
          final item = playbackQueue[index];
          playbackQueue[index] = item.copyWith(
            cachedPath: completedPayload['path']?.toString(),
            cachedMeta: completedPayload,
            title: completedPayload['title']?.toString() ?? item.title,
          );
        }
        cachedVideo = completedPayload;
        downloadProgress = {
          ...completedPayload,
          'status': 'complete',
          'phase': 'Complete',
          'percent': 1.0,
          'filename': completedPayload['path'],
        };
        activeDownloadTaskId = null;
        activeDownloadQueueIndex = null;
        activeDownloadSourceUrl = null;
        playAfterDownload = false;
        status = 'Cached to ${completedPayload['path']}';
      });
      if (shouldPlayAfterDownload) {
        unawaited(_playCachedVideo(completedPayload));
      } else if (queueIndexToPlay != null) {
        unawaited(_playQueueItem(queueIndexToPlay));
      } else {
        unawaited(_maybePrefetchNextQueueVideo());
      }
    } else if (event == 'download_failed') {
      setState(() {
        activeDownloadTaskId = null;
        activeDownloadQueueIndex = null;
        activeDownloadSourceUrl = null;
        playAfterDownload = false;
        if (payload['status'] == 'cancelled') {
          downloadProgress = {
            ...payload,
            'phase': 'Cancelled',
          };
          status = 'Download cancelled';
        } else {
          downloadProgress = null;
          status = '${payload['status']}: ${payload['error']}';
        }
      });
    } else if (event == 'download_cancel_requested') {
      setState(() {
        playAfterDownload = false;
        activeDownloadSourceUrl = null;
        downloadProgress = {
          ...payload,
          'phase': 'Cancelling',
        };
        status = 'Cancelling download...';
      });
    }
  }

  Future<void> _pollPlaybackStatus() async {
    if (pollingStatus) {
      return;
    }
    pollingStatus = true;
    try {
      final result = await bridge.send('playback_status', {});
      if (!mounted) {
        return;
      }
      final sample = StatusSample.fromStatus(result);
      setState(() {
        playbackStatus = result;
        statusSamples.add(sample);
        if (statusSamples.length > 90) {
          statusSamples.removeRange(0, statusSamples.length - 90);
        }
      });
      _maybeAdvanceQueue(result);
    } catch (error) {
      if (mounted) {
        setState(() => playbackStatus = {
              ...playbackStatus,
              'state': 'ERROR',
              'status': error.toString(),
            });
      }
    } finally {
      pollingStatus = false;
    }
  }

  Future<void> _refreshSources() async {
    await _run('Refreshing capture sources...', () async {
      final windowResult = await bridge.send('windows', {});
      final monitorResult = await bridge.send('monitors', {});
      setState(() {
        windows
          ..clear()
          ..addAll((windowResult['windows'] as List? ?? [])
              .map((item) => (item as Map).cast<String, dynamic>()));
        monitors
          ..clear()
          ..addAll((monitorResult['monitors'] as List? ?? [])
              .map((item) => (item as Map).cast<String, dynamic>()));
        selectedWindowIndex = windows.isEmpty ? null : 0;
        selectedMonitorIndex = 0;
        status = 'Capture sources refreshed';
      });
    });
  }

  Future<void> _refreshState() async {
    try {
      final result = await bridge.send('state', {});
      if (!mounted) {
        return;
      }
      setState(() {
        cacheDir = result['cache_dir']?.toString() ?? cacheDir;
      });
    } catch (_) {
      // State refresh is informational; primary controls should remain usable.
    }
  }

  Future<void> _pickFile() async {
    try {
      setState(() => status = 'Opening file picker...');
      final result = await bridge.send('pick_file', {});
      final path = result['path']?.toString() ?? '';
      if (path.isEmpty) {
        setState(() => status = 'File selection cancelled');
        return;
      }
      setState(() {
        selectedFile = path;
        status = selectedFile!;
      });
    } catch (error) {
      setState(() => status = error.toString());
    }
  }

  Future<void> _pickFilesForQueue() async {
    try {
      setState(() => status = 'Opening file picker...');
      final result = await bridge.send('pick_files', {});
      final paths = (result['paths'] as List? ?? [])
          .map((item) => item.toString())
          .where((item) => item.isNotEmpty)
          .toList();
      if (paths.isEmpty) {
        setState(() => status = 'File selection cancelled');
        return;
      }
      final range =
          _readTimeRange(mediaStartController.text, mediaEndController.text);
      if (range == null) {
        return;
      }
      setState(() {
        selectedFile = paths.first;
        playbackQueue.addAll([
          for (final path in paths)
            PlaybackQueueItem(
              kind: QueueItemKind.media,
              source: path,
              title: _basename(path),
              startSeconds: range.startSeconds,
              endSeconds: range.endSeconds,
            ),
        ]);
        status = 'Added ${paths.length} file(s) to queue';
      });
    } catch (error) {
      setState(() => status = error.toString());
    }
  }

  Future<void> _playFile() async {
    final device = selectedDevice;
    final path = selectedFile;
    if (device == null || path == null) {
      setState(() => status = 'Select a device and media file first');
      return;
    }
    await _run('Starting media playback...', () async {
      final position = _normalizePosition(mediaStartController.text);
      await bridge.send('play_media',
          {'device': device.data, 'path': path, 'position': position});
      final suffix = position.isEmpty ? '' : ' from $position';
      setState(
          () => status = 'Playing ${_basename(path)} on ${device.name}$suffix');
      unawaited(_pollPlaybackStatus());
    });
  }

  void _addSelectedFileToQueue() {
    final path = selectedFile;
    if (path == null || path.isEmpty) {
      setState(() => status = 'Select a media file first');
      return;
    }
    final range =
        _readTimeRange(mediaStartController.text, mediaEndController.text);
    if (range == null) {
      return;
    }
    setState(() {
      playbackQueue.add(PlaybackQueueItem(
        kind: QueueItemKind.media,
        source: path,
        title: _basename(path),
        startSeconds: range.startSeconds,
        endSeconds: range.endSeconds,
      ));
      status = 'Added ${_basename(path)} to queue';
    });
  }

  Future<void> _playLive() async {
    final device = selectedDevice;
    final url = liveController.text.trim();
    if (device == null || url.isEmpty) {
      setState(() => status = 'Select a device and enter a live URL first');
      return;
    }
    await _run('Resolving live stream...', () async {
      await bridge.send('play_live', {
        'device': device.data,
        'url': url,
        'video_bitrate': '${bitrate.round()}k',
      });
      setState(() => status = 'Live stream playing on ${device.name}');
      unawaited(_pollPlaybackStatus());
    });
  }

  Future<void> _inspectVideo() async {
    final url = videoController.text.trim();
    if (url.isEmpty) {
      setState(() => status = 'Enter a video URL first');
      return;
    }
    await _run('Inspecting video...', () async {
      final result = await bridge.send('inspect_video', {'url': url});
      setState(() {
        inspectedVideo = {...result, 'source_url': url};
        cachedVideo = null;
        status = '${result['title']}  ${result['duration_string'] ?? ''}';
      });
    });
  }

  void _addVideoUrlToQueue() {
    final url = videoController.text.trim();
    if (url.isEmpty) {
      setState(() => status = 'Enter a video URL first');
      return;
    }
    final urlStart = _parsePositionSecondsFromUrl(url);
    final range = _readTimeRange(
      videoStartController.text,
      videoEndController.text,
      fallbackStart: urlStart ?? 0,
    );
    if (range == null) {
      return;
    }
    final item = videoQueueItemForTest(
      url: url,
      inspectedVideo: inspectedVideo,
      cachedVideo: cachedVideo,
      startSeconds: range.startSeconds,
      endSeconds: range.endSeconds,
    );
    setState(() {
      playbackQueue.add(item);
      status = 'Added video URL to queue';
    });
    unawaited(_maybePrefetchNextQueueVideo());
  }

  Future<void> _cacheAndPlayVideo() async {
    final device = selectedDevice;
    final url = videoController.text.trim();
    if (device == null || url.isEmpty) {
      setState(() => status = 'Select a device and enter a video URL first');
      return;
    }
    await _run('Starting cache task...', () async {
      setState(() {
        activeDownloadSourceUrl = url;
        playAfterDownload = true;
        downloadProgress = {'status': 'starting', 'percent': 0.0};
      });
      final started = await bridge.send('cache_video', {'url': url});
      setState(() {
        activeDownloadTaskId = started['task_id']?.toString();
        status = 'Caching video...';
      });
    });
  }

  Future<void> _playCachedVideo(Map<String, dynamic> cached) async {
    final device = selectedDevice;
    if (device == null) {
      setState(() => status = 'Cache completed; select a device to play');
      return;
    }
    await _run('Starting cached playback...', () async {
      await bridge.send('play_cached_video', {
        'device': device.data,
        'path': cached['path'],
        'position': cached['start_position'] ?? '00:00:00',
      });
      setState(() {
        cachedVideo = cached;
        inspectedVideo = cached;
        status = 'Playing ${cached['title']} from ${cached['start_position']}';
      });
      unawaited(_pollPlaybackStatus());
    });
  }

  Future<void> _startQueue() async {
    if (selectedDevice == null) {
      setState(() => status = 'Select a device first');
      return;
    }
    if (playbackQueue.isEmpty) {
      setState(() => status = 'Add at least one queue item first');
      return;
    }
    setState(() {
      queueActive = true;
      queueAdvancing = false;
      currentQueueIndex = -1;
    });
    await _playQueueItem(0);
  }

  void _stopQueue() {
    setState(() {
      queueActive = false;
      queueAdvancing = false;
      currentQueueIndex = -1;
      status = 'Queue stopped';
    });
  }

  Future<void> _playQueueItem(int index) async {
    final device = selectedDevice;
    if (device == null || index < 0 || index >= playbackQueue.length) {
      setState(() {
        _resetQueuePlaybackState();
        status = 'Queue finished';
      });
      return;
    }
    final item = playbackQueue[index];
    setState(() {
      queueAdvancing = true;
      currentQueueIndex = index;
      status = 'Starting queue item ${index + 1}/${playbackQueue.length}';
    });
    try {
      final position = _formatDuration(item.startSeconds);
      if (item.kind == QueueItemKind.media) {
        await bridge.send('play_media',
            {'device': device.data, 'path': item.source, 'position': position});
      } else {
        final path = item.cachedPath;
        if (path == null || path.isEmpty) {
          if (activeDownloadQueueIndex == index) {
            setState(() {
              playAfterDownload = false;
              status =
                  'Waiting for queue item ${index + 1}/${playbackQueue.length} to finish caching...';
            });
            return;
          }
          setState(() {
            activeDownloadQueueIndex = index;
            activeDownloadSourceUrl = item.source;
            playAfterDownload = false;
            downloadProgress = {'status': 'starting', 'percent': 0.0};
            status =
                'Caching queue item ${index + 1}/${playbackQueue.length}...';
          });
          final started =
              await bridge.send('cache_video', {'url': item.source});
          setState(() {
            if (activeDownloadQueueIndex == index) {
              activeDownloadTaskId = started['task_id']?.toString();
            }
          });
          return;
        }
        await bridge.send('play_cached_video',
            {'device': device.data, 'path': path, 'position': position});
      }
      setState(() {
        queueAdvancing = false;
        status =
            'Playing queue item ${index + 1}/${playbackQueue.length}: ${item.title}';
      });
      unawaited(_maybePrefetchNextQueueVideo());
      unawaited(_pollPlaybackStatus());
    } catch (error) {
      setState(() {
        _resetQueuePlaybackState();
        status = error.toString();
      });
    }
  }

  void _maybeAdvanceQueue(Map<String, dynamic> statusResult) {
    if (!queueActive ||
        queueAdvancing ||
        currentQueueIndex < 0 ||
        currentQueueIndex >= playbackQueue.length) {
      return;
    }
    final endSeconds = playbackQueue[currentQueueIndex].endSeconds;
    if (endSeconds == null) {
      final state = statusResult['state']?.toString() ?? '';
      if (state == 'STOPPED' || state == 'NO_MEDIA_PRESENT') {
        unawaited(_playQueueItem(currentQueueIndex + 1));
      }
      return;
    }
    final position = (statusResult['position_seconds'] as num?)?.toInt() ?? 0;
    if (position >= endSeconds) {
      unawaited(_playQueueItem(currentQueueIndex + 1));
    }
  }

  Future<void> _maybePrefetchNextQueueVideo() async {
    if (!queueActive) {
      return;
    }
    final index = nextQueueVideoToCacheForTest(
      playbackQueue,
      currentQueueIndex: currentQueueIndex,
      activeDownloadTaskId: activeDownloadTaskId,
      activeDownloadQueueIndex: activeDownloadQueueIndex,
      playAfterDownload: playAfterDownload,
    );
    if (index == null) {
      return;
    }
    final item = playbackQueue[index];
    setState(() {
      activeDownloadQueueIndex = index;
      activeDownloadSourceUrl = item.source;
      playAfterDownload = false;
      downloadProgress = {'status': 'starting', 'percent': 0.0};
      status = 'Caching queue item ${index + 1}/${playbackQueue.length}...';
    });
    try {
      final started = await bridge.send('cache_video', {'url': item.source});
      if (!mounted) {
        return;
      }
      setState(() {
        if (activeDownloadQueueIndex == index) {
          activeDownloadTaskId = started['task_id']?.toString();
        }
      });
    } catch (error) {
      if (!mounted) {
        return;
      }
      setState(() {
        if (activeDownloadQueueIndex == index) {
          activeDownloadTaskId = null;
          activeDownloadQueueIndex = null;
          activeDownloadSourceUrl = null;
          downloadProgress = null;
        }
        status = error.toString();
      });
    }
  }

  void _removeQueueItem(int index) {
    if (index < 0 || index >= playbackQueue.length) {
      return;
    }
    setState(() {
      playbackQueue.removeAt(index);
      if (currentQueueIndex == index) {
        _resetQueuePlaybackState();
      } else if (currentQueueIndex > index) {
        currentQueueIndex -= 1;
      }
      status = 'Removed queue item';
    });
  }

  void _clearQueue() {
    setState(() {
      playbackQueue.clear();
      _resetQueuePlaybackState();
      status = 'Queue cleared';
    });
  }

  void _resetQueuePlaybackState() {
    queueActive = false;
    queueAdvancing = false;
    currentQueueIndex = -1;
    activeDownloadQueueIndex = null;
    activeDownloadSourceUrl = null;
  }

  TimeRange? _readTimeRange(String startInput, String endInput,
      {int fallbackStart = 0}) {
    final startText = startInput.trim();
    final endText = endInput.trim();
    final start =
        startText.isEmpty ? fallbackStart : _parsePositionSeconds(startText);
    final end = endText.isEmpty ? null : _parsePositionSeconds(endText);
    if (start == null) {
      setState(() => status = 'Invalid start time');
      return null;
    }
    if (endText.isNotEmpty && end == null) {
      setState(() => status = 'Invalid end time');
      return null;
    }
    if (end != null && end <= start) {
      setState(() => status = 'End time must be later than start time');
      return null;
    }
    return TimeRange(startSeconds: start, endSeconds: end);
  }

  Future<void> _cancelCache() async {
    final taskId = activeDownloadTaskId;
    if (taskId == null) {
      return;
    }
    final cancellingQueueDownload = activeDownloadQueueIndex != null;
    setState(() {
      status = 'Cancelling download...';
      playAfterDownload = false;
      downloadProgress = {
        ...?downloadProgress,
        'task_id': taskId,
        'status': 'cancel_requested',
        'phase': 'Cancelling',
      };
      activeDownloadQueueIndex = null;
      activeDownloadSourceUrl = null;
      if (cancellingQueueDownload) {
        _resetQueuePlaybackState();
      }
    });
    try {
      await bridge.send('cancel_cache', {'task_id': taskId});
    } catch (error) {
      if (mounted) {
        setState(() => status = error.toString());
      }
    }
  }

  Future<void> _seekTo(double seconds) async {
    if (seeking) {
      return;
    }
    setState(() => seeking = true);
    try {
      final result = await bridge.send('seek', {'seconds': seconds.round()});
      setState(() => status = 'Seeked to ${result['position']}');
      unawaited(_pollPlaybackStatus());
    } catch (error) {
      setState(() => status = error.toString());
    } finally {
      if (mounted) {
        setState(() => seeking = false);
      }
    }
  }

  Future<void> _castWindow() async {
    final device = selectedDevice;
    final index = selectedWindowIndex;
    if (device == null || index == null || index >= windows.length) {
      setState(() => status = 'Select a device and window first');
      return;
    }
    final window = windows[index];
    await _run('Starting window cast...', () async {
      await bridge.send('cast_window', {
        'device': device.data,
        'hwnd': window['hwnd'],
        'label': window['title'],
        'fps': fps.round(),
        'video_bitrate': '${bitrate.round()}k',
      });
      setState(() => status = 'Casting ${window['title']} to ${device.name}');
      unawaited(_pollPlaybackStatus());
    });
  }

  Future<void> _castScreen() async {
    final device = selectedDevice;
    if (device == null || monitors.isEmpty) {
      setState(() => status = 'Select a device and monitor first');
      return;
    }
    final monitor =
        monitors[selectedMonitorIndex.clamp(0, monitors.length - 1).toInt()];
    await _run('Starting screen cast...', () async {
      await bridge.send('cast_screen', {
        'device': device.data,
        'monitor_index': monitor['index'],
        'label': monitor['name'],
        'fps': fps.round(),
        'video_bitrate': '${bitrate.round()}k',
      });
      setState(() => status = 'Casting ${monitor['name']} to ${device.name}');
      unawaited(_pollPlaybackStatus());
    });
  }

  Future<void> _stop() async {
    await _run('Stopping playback...', () async {
      await bridge.send('stop', {});
      setState(() => status = 'Stopped');
      unawaited(_pollPlaybackStatus());
    });
  }

  Future<void> _setVolume(double value) async {
    setState(() => volume = value);
  }

  Future<void> _applyVolume(double value) async {
    setState(() => volume = value);
    final device = selectedDevice;
    if (device == null) {
      return;
    }
    try {
      await bridge
          .send('set_volume', {'device': device.data, 'volume': value.round()});
    } catch (error) {
      setState(() => status = error.toString());
    }
  }

  void _setBitrate(double value) {
    setState(() => bitrate = value);
  }

  void _applyBitrate(double value) {
    setState(() => bitrate = value);
    _scheduleStreamRestart();
  }

  void _setFps(double value) {
    setState(() => fps = value);
  }

  void _applyFps(double value) {
    setState(() => fps = value);
    _scheduleStreamRestart();
  }

  void _scheduleStreamRestart() {
    bitrateDebounce?.cancel();
    bitrateDebounce = Timer(const Duration(milliseconds: 250),
        () => unawaited(_applyStreamRestart()));
  }

  Future<void> _applyStreamRestart() async {
    if (playbackStatus['playing'] != true) {
      return;
    }
    final sourceType = playbackStatus['source_type']?.toString() ?? '';
    if (!{'live', 'window', 'screen'}.contains(sourceType)) {
      setState(() => status = 'Bitrate applies to live/window/screen streams');
      return;
    }
    try {
      setState(() => status =
          'Restarting stream at ${bitrate.round()}k / ${fps.round()} fps...');
      final result = await bridge.send('restart_stream', {
        'video_bitrate': '${bitrate.round()}k',
        'fps': fps.round(),
      });
      setState(() => status = result['status'] == 'skipped'
          ? result['reason'].toString()
          : 'Stream restarted at ${bitrate.round()}k / ${fps.round()} fps');
      unawaited(_pollPlaybackStatus());
    } catch (error) {
      setState(() => status = error.toString());
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Row(
          children: [
            SizedBox(
              width: 310,
              child: _sidePanel(),
            ),
            const VerticalDivider(width: 1),
            Expanded(child: _mainPanel()),
          ],
        ),
      ),
    );
  }

  Widget _sidePanel() {
    return Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text('Auto-Cast', style: Theme.of(context).textTheme.headlineSmall),
          const SizedBox(height: 14),
          FilledButton.icon(
            onPressed: busy ? null : _scan,
            icon: busy
                ? const SizedBox.square(
                    dimension: 18,
                    child: CircularProgressIndicator(strokeWidth: 2))
                : const Icon(Icons.radar),
            label: const Text('Scan Devices'),
          ),
          const SizedBox(height: 12),
          Expanded(
            child: ListView.separated(
              itemCount: devices.length,
              separatorBuilder: (_, __) => const SizedBox(height: 8),
              itemBuilder: (context, index) {
                final device = devices[index];
                final selected = identical(device, selectedDevice);
                return ListTile(
                  selected: selected,
                  shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(8)),
                  tileColor: selected
                      ? Theme.of(context).colorScheme.primaryContainer
                      : Theme.of(context).colorScheme.surfaceContainerHighest,
                  leading: const Icon(Icons.tv),
                  title: Text(device.name,
                      maxLines: 1, overflow: TextOverflow.ellipsis),
                  subtitle: Text(device.subtitle,
                      maxLines: 1, overflow: TextOverflow.ellipsis),
                  onTap: () => setState(() => selectedDevice = device),
                );
              },
            ),
          ),
          const SizedBox(height: 12),
          FilledButton.tonalIcon(
            onPressed: busy ? null : _stop,
            icon: const Icon(Icons.stop),
            label: const Text('Stop'),
          ),
        ],
      ),
    );
  }

  Widget _mainPanel() {
    return Padding(
      padding: const EdgeInsets.all(20),
      child: SingleChildScrollView(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            _statusBar(),
            const SizedBox(height: 16),
            _playbackOverview(),
            const SizedBox(height: 16),
            _modeCards(),
            const SizedBox(height: 16),
            _controlWorkspace(),
            const SizedBox(height: 16),
            _sliders(),
          ],
        ),
      ),
    );
  }

  Widget _modeCards() {
    return LayoutBuilder(
      builder: (context, constraints) {
        final cardWidth = constraints.maxWidth < 760
            ? (constraints.maxWidth - 12) / 2
            : (constraints.maxWidth - 36) / 4;
        return Wrap(
          spacing: 12,
          runSpacing: 12,
          children: [
            for (final mode in CastMode.values)
              SizedBox(
                width: cardWidth,
                child: _modeCard(mode),
              ),
          ],
        );
      },
    );
  }

  Widget _modeCard(CastMode mode) {
    final selected = mode == selectedMode;
    return InkWell(
      borderRadius: BorderRadius.circular(8),
      onTap: () => setState(() => selectedMode = mode),
      child: DecoratedBox(
        decoration: BoxDecoration(
          color: selected
              ? Theme.of(context).colorScheme.primaryContainer
              : Theme.of(context).colorScheme.surface,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(
              color: selected
                  ? Theme.of(context).colorScheme.primary
                  : Theme.of(context).colorScheme.outlineVariant),
        ),
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Row(
            children: [
              Icon(mode.icon),
              const SizedBox(width: 10),
              Expanded(
                  child: Text(mode.label,
                      maxLines: 1, overflow: TextOverflow.ellipsis)),
            ],
          ),
        ),
      ),
    );
  }

  Widget _activeModePanel() {
    return switch (selectedMode) {
      CastMode.media => _mediaControls(),
      CastMode.video => _videoUrlControls(),
      CastMode.live => _liveControls(),
      CastMode.capture => _captureControls(),
    };
  }

  Widget _controlWorkspace() {
    return LayoutBuilder(
      builder: (context, constraints) {
        final controls = _activeModePanel();
        final queue = _queuePanel();
        if (constraints.maxWidth < 980) {
          return Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              controls,
              const SizedBox(height: 16),
              queue,
            ],
          );
        }
        return Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(flex: 6, child: controls),
            const SizedBox(width: 16),
            Expanded(flex: 5, child: queue),
          ],
        );
      },
    );
  }

  Widget _statusBar() {
    return DecoratedBox(
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Row(
          children: [
            Icon(busy ? Icons.sync : Icons.info_outline),
            const SizedBox(width: 10),
            Expanded(
                child:
                    Text(status, maxLines: 2, overflow: TextOverflow.ellipsis)),
            const SizedBox(width: 12),
            Text('Auto Resume', style: Theme.of(context).textTheme.labelMedium),
            Switch(value: autoSearchResume, onChanged: _setAutoSearchResume),
          ],
        ),
      ),
    );
  }

  Widget _playbackOverview() {
    final playing = playbackStatus['playing'] == true;
    final state = playbackStatus['state']?.toString() ?? 'UNKNOWN';
    final detail = playbackStatus['status']?.toString() ?? '';
    final sourceType = playbackStatus['source_type']?.toString() ?? '';
    final position = playbackStatus['position']?.toString() ?? '';
    final duration = playbackStatus['duration']?.toString() ?? '';
    final positionSeconds =
        (playbackStatus['position_seconds'] as num?)?.toDouble() ?? 0;
    final durationSeconds =
        (playbackStatus['duration_seconds'] as num?)?.toDouble() ?? 0;
    final volumeValue = playbackStatus['volume'];
    final latencyMs = playbackStatus['latency_ms'];
    final checkedAt = (playbackStatus['checked_at'] as num?)?.toDouble();
    final playRate = _recentPlaybackRate(statusSamples);
    final showTvMetrics = playing;
    final statusColor = switch (state) {
      'PLAYING' => Colors.greenAccent,
      'PAUSED_PLAYBACK' => Colors.amberAccent,
      'STOPPED' || 'NO_MEDIA_PRESENT' => Colors.orangeAccent,
      'ERROR' => Colors.redAccent,
      _ => Theme.of(context).colorScheme.primary,
    };
    return DecoratedBox(
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surface,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: Theme.of(context).colorScheme.outlineVariant),
      ),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Row(
          children: [
            SizedBox(
              width: 210,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Icon(playing ? Icons.cast_connected : Icons.cast,
                          color: statusColor),
                      const SizedBox(width: 8),
                      Expanded(
                          child: Text(state,
                              style: Theme.of(context).textTheme.titleMedium)),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Text(detail.isEmpty ? 'Waiting for playback status' : detail,
                      maxLines: 2, overflow: TextOverflow.ellipsis),
                  const SizedBox(height: 8),
                  Text('Source ${sourceType.isEmpty ? '--' : sourceType}'),
                  Text(
                      'Pos ${position.isEmpty ? '--' : position}/${duration.isEmpty ? '--' : duration}'),
                  Text('Vol ${volumeValue == null ? '--' : '$volumeValue%'}'),
                  Text(
                      'TV latency ${showTvMetrics && latencyMs != null ? '${latencyMs}ms' : '--'}'),
                  Text(
                      'Last check ${showTvMetrics && checkedAt != null ? _formatClock(checkedAt) : '--'}'),
                  Text(
                      'Rate ${showTvMetrics && playRate != null ? '${playRate.toStringAsFixed(2)}x' : '--'}'),
                  if (durationSeconds > 0)
                    Slider(
                      value: positionSeconds.clamp(0, durationSeconds),
                      min: 0,
                      max: durationSeconds,
                      divisions: durationSeconds > 0
                          ? durationSeconds.round().clamp(1, 1000)
                          : null,
                      label: _formatDuration(positionSeconds.round()),
                      onChangeEnd: seeking ? null : _seekTo,
                      onChanged: (_) {},
                    ),
                ],
              ),
            ),
            const SizedBox(width: 16),
            Expanded(
              child: SizedBox(
                height: 112,
                child: StatusChart(samples: statusSamples),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _mediaControls() {
    final rangeLabel = _rangePreview(
        mediaStartController.text, mediaEndController.text,
        fallbackStart: 0);
    return _panel(
      title: 'Media File',
      icon: Icons.video_file,
      children: [
        Wrap(
          spacing: 10,
          runSpacing: 10,
          children: [
            OutlinedButton.icon(
                onPressed: busy ? null : _pickFile,
                icon: const Icon(Icons.folder_open),
                label: const Text('Choose File')),
            OutlinedButton.icon(
                onPressed: busy ? null : _pickFilesForQueue,
                icon: const Icon(Icons.playlist_add),
                label: const Text('Choose Multiple')),
          ],
        ),
        const SizedBox(height: 10),
        Text(
            selectedFile == null
                ? 'No file selected'
                : _basename(selectedFile!),
            maxLines: 2,
            overflow: TextOverflow.ellipsis),
        const SizedBox(height: 10),
        Text(rangeLabel, style: Theme.of(context).textTheme.labelMedium),
        const SizedBox(height: 10),
        Row(
          children: [
            Expanded(
              child: TextField(
                controller: mediaStartController,
                decoration: const InputDecoration(
                    labelText: 'Start time', border: OutlineInputBorder()),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: TextField(
                controller: mediaEndController,
                decoration: const InputDecoration(
                    labelText: 'End time', border: OutlineInputBorder()),
              ),
            ),
          ],
        ),
        const SizedBox(height: 14),
        Wrap(
          spacing: 10,
          runSpacing: 10,
          children: [
            FilledButton.icon(
                onPressed: busy ? null : _playFile,
                icon: const Icon(Icons.play_arrow),
                label: const Text('Play File')),
            FilledButton.tonalIcon(
                onPressed: busy ? null : _addSelectedFileToQueue,
                icon: const Icon(Icons.queue),
                label: const Text('Add to Queue')),
          ],
        ),
      ],
    );
  }

  Widget _liveControls() {
    return _panel(
      title: 'Live URL',
      icon: Icons.live_tv,
      children: [
        TextField(
          controller: liveController,
          decoration: const InputDecoration(
              labelText: 'Live URL', border: OutlineInputBorder()),
        ),
        const SizedBox(height: 24),
        FilledButton.icon(
            onPressed: busy ? null : _playLive,
            icon: const Icon(Icons.cast),
            label: const Text('Play Live')),
      ],
    );
  }

  Widget _videoUrlControls() {
    final video = inspectedVideo;
    final title = video?['title']?.toString();
    final duration = video?['duration_string']?.toString();
    final start = video?['start_time']?.toString();
    final progress = downloadProgress;
    final percent = progress == null
        ? null
        : downloadProgressIndicatorValueForTest(progress);
    final path =
        cachedVideo?['path']?.toString() ?? progress?['filename']?.toString();
    final urlStart = _parsePositionSecondsFromUrl(videoController.text) ?? 0;
    final rangeLabel = _rangePreview(
        videoStartController.text, videoEndController.text,
        fallbackStart: urlStart);
    return _panel(
      title: 'Video URL',
      icon: Icons.ondemand_video,
      children: [
        TextField(
          controller: videoController,
          decoration: const InputDecoration(
              labelText: 'Bilibili or video page URL',
              border: OutlineInputBorder()),
        ),
        const SizedBox(height: 10),
        Text(rangeLabel, style: Theme.of(context).textTheme.labelMedium),
        const SizedBox(height: 10),
        Row(
          children: [
            Expanded(
              child: TextField(
                controller: videoStartController,
                decoration: const InputDecoration(
                    labelText: 'Start time', border: OutlineInputBorder()),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: TextField(
                controller: videoEndController,
                decoration: const InputDecoration(
                    labelText: 'End time / next video',
                    border: OutlineInputBorder()),
              ),
            ),
          ],
        ),
        const SizedBox(height: 10),
        Wrap(
          spacing: 10,
          runSpacing: 10,
          children: [
            OutlinedButton.icon(
                onPressed: busy ? null : _inspectVideo,
                icon: const Icon(Icons.info_outline),
                label: const Text('Inspect')),
            FilledButton.tonalIcon(
                onPressed: busy ? null : _addVideoUrlToQueue,
                icon: const Icon(Icons.playlist_add),
                label: const Text('Add to Queue')),
          ],
        ),
        const SizedBox(height: 10),
        if (title != null)
          Text(title, maxLines: 2, overflow: TextOverflow.ellipsis),
        if (duration != null)
          Text('Duration $duration  Start ${start ?? '0'}s'),
        const SizedBox(height: 8),
        Text('Cache folder ${cacheDir.isEmpty ? '--' : cacheDir}',
            maxLines: 1, overflow: TextOverflow.ellipsis),
        if (path != null && path.isNotEmpty)
          Text('File $path', maxLines: 2, overflow: TextOverflow.ellipsis),
        if (progress != null) ...[
          const SizedBox(height: 8),
          LinearProgressIndicator(value: percent?.clamp(0.0, 1.0)),
          const SizedBox(height: 6),
          Text(_downloadProgressText(progress)),
          if (activeDownloadTaskId != null) ...[
            const SizedBox(height: 8),
            OutlinedButton.icon(
              onPressed: downloadProgress?['status'] == 'cancel_requested'
                  ? null
                  : _cancelCache,
              icon: const Icon(Icons.cancel),
              label: const Text('Cancel Download'),
            ),
          ],
        ],
        const SizedBox(height: 14),
        FilledButton.icon(
            onPressed: busy ? null : _cacheAndPlayVideo,
            icon: const Icon(Icons.download_for_offline),
            label: const Text('Cache & Play')),
      ],
    );
  }

  Widget _queuePanel() {
    final readyCount = playbackQueue.where((item) => item.isReady).length;
    final queueSummary = playbackQueue.isEmpty
        ? 'No items'
        : '$readyCount/${playbackQueue.length} ready';
    return _panel(
      title: 'Playback Queue',
      icon: Icons.queue_music,
      children: [
        Row(
          children: [
            Icon(
              queueActive ? Icons.play_circle : Icons.list_alt,
              color: queueActive
                  ? Theme.of(context).colorScheme.primary
                  : Theme.of(context).colorScheme.onSurfaceVariant,
            ),
            const SizedBox(width: 8),
            Expanded(
              child: Text(queueActive
                  ? 'Playing ${currentQueueIndex + 1}/${playbackQueue.length}'
                  : queueSummary),
            ),
          ],
        ),
        const SizedBox(height: 12),
        ConstrainedBox(
          constraints: const BoxConstraints(maxHeight: 300),
          child: playbackQueue.isEmpty
              ? DecoratedBox(
                  decoration: BoxDecoration(
                    color:
                        Theme.of(context).colorScheme.surfaceContainerHighest,
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: const Padding(
                    padding: EdgeInsets.all(18),
                    child: Center(child: Text('No queued videos')),
                  ),
                )
              : ListView.separated(
                  shrinkWrap: true,
                  itemCount: playbackQueue.length,
                  separatorBuilder: (_, __) => const Divider(height: 12),
                  itemBuilder: (context, index) =>
                      _queueTile(index, playbackQueue[index]),
                ),
        ),
        const SizedBox(height: 12),
        Wrap(
          spacing: 10,
          runSpacing: 10,
          children: [
            FilledButton.icon(
              onPressed: busy || playbackQueue.isEmpty ? null : _startQueue,
              icon: const Icon(Icons.playlist_play),
              label: const Text('Start Queue'),
            ),
            OutlinedButton.icon(
              onPressed: queueActive ? _stopQueue : null,
              icon: const Icon(Icons.stop_circle),
              label: const Text('Stop Queue'),
            ),
            OutlinedButton.icon(
              onPressed:
                  playbackQueue.isEmpty || queueActive ? null : _clearQueue,
              icon: const Icon(Icons.clear_all),
              label: const Text('Clear'),
            ),
          ],
        ),
      ],
    );
  }

  Widget _queueTile(int index, PlaybackQueueItem item) {
    final active = queueActive && currentQueueIndex == index;
    final range =
        '${_formatDuration(item.startSeconds)} -> ${item.endSeconds == null ? 'end' : _formatDuration(item.endSeconds!)}';
    final stateLabel =
        item.kind == QueueItemKind.video && item.cachedPath == null
            ? 'cache pending'
            : 'ready';
    final statusColor = active
        ? Theme.of(context).colorScheme.primary
        : item.isReady
            ? Colors.green
            : Theme.of(context).colorScheme.tertiary;
    return ListTile(
      dense: true,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
      tileColor: active
          ? Theme.of(context).colorScheme.primaryContainer
          : Theme.of(context).colorScheme.surfaceContainerHighest,
      contentPadding: const EdgeInsets.symmetric(horizontal: 10, vertical: 2),
      leading: CircleAvatar(
        radius: 16,
        backgroundColor: statusColor.withValues(alpha: 0.18),
        foregroundColor: statusColor,
        child: Text('${index + 1}'),
      ),
      title: Text(item.title, maxLines: 1, overflow: TextOverflow.ellipsis),
      subtitle: Text('$range  ${item.kind.name}  $stateLabel',
          maxLines: 1, overflow: TextOverflow.ellipsis),
      trailing: IconButton(
        tooltip: 'Remove',
        onPressed: active ? null : () => _removeQueueItem(index),
        icon: const Icon(Icons.delete_outline),
      ),
      selected: active,
    );
  }

  Widget _captureControls() {
    return _panel(
      title: 'Capture',
      icon: Icons.screenshot_monitor,
      children: [
        OutlinedButton.icon(
            onPressed: busy ? null : _refreshSources,
            icon: const Icon(Icons.refresh),
            label: const Text('Refresh Sources')),
        const SizedBox(height: 10),
        DropdownButtonFormField<int>(
          initialValue: selectedWindowIndex,
          decoration: const InputDecoration(
              labelText: 'Window', border: OutlineInputBorder()),
          items: [
            for (var i = 0; i < windows.length; i++)
              DropdownMenuItem(
                  value: i,
                  child: Text(windows[i]['title']?.toString() ?? 'Window $i',
                      overflow: TextOverflow.ellipsis)),
          ],
          onChanged: (value) => setState(() => selectedWindowIndex = value),
        ),
        const SizedBox(height: 10),
        FilledButton.tonalIcon(
            onPressed: busy ? null : _castWindow,
            icon: const Icon(Icons.web_asset),
            label: const Text('Cast Window')),
        const SizedBox(height: 14),
        DropdownButtonFormField<int>(
          initialValue: monitors.isEmpty ? null : selectedMonitorIndex,
          decoration: const InputDecoration(
              labelText: 'Monitor', border: OutlineInputBorder()),
          items: [
            for (var i = 0; i < monitors.length; i++)
              DropdownMenuItem(
                  value: i,
                  child: Text(monitors[i]['name']?.toString() ?? 'Monitor $i')),
          ],
          onChanged: (value) =>
              setState(() => selectedMonitorIndex = value ?? 0),
        ),
        const SizedBox(height: 10),
        FilledButton.icon(
            onPressed: busy ? null : _castScreen,
            icon: const Icon(Icons.desktop_windows),
            label: const Text('Cast Screen')),
      ],
    );
  }

  Widget _sliders() {
    return DecoratedBox(
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(8),
      ),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final rows = [
            _sliderRow(
                Icons.volume_up,
                Slider(
                    value: volume,
                    min: 0,
                    max: 100,
                    divisions: 20,
                    label: '${volume.round()}%',
                    onChanged: _setVolume,
                    onChangeEnd: _applyVolume),
                '${volume.round()}%'),
            _sliderRow(
                Icons.speed,
                Slider(
                    value: bitrate,
                    min: 1000,
                    max: 8000,
                    divisions: 14,
                    label: '${bitrate.round()}k',
                    onChanged: _setBitrate,
                    onChangeEnd: _applyBitrate),
                '${bitrate.round()}k'),
            _sliderRow(
                Icons.motion_photos_on,
                Slider(
                    value: fps,
                    min: 5,
                    max: 30,
                    divisions: 5,
                    label: '${fps.round()} fps',
                    onChanged: _setFps,
                    onChangeEnd: _applyFps),
                '${fps.round()} fps'),
          ];
          return Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
            child: constraints.maxWidth < 820
                ? Column(children: rows)
                : Row(
                    children: rows.map((row) => Expanded(child: row)).toList()),
          );
        },
      ),
    );
  }

  Widget _sliderRow(IconData icon, Slider slider, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(
        children: [
          Icon(icon),
          Expanded(child: slider),
          SizedBox(width: 64, child: Text(value, textAlign: TextAlign.end)),
        ],
      ),
    );
  }

  Widget _panel(
      {required String title,
      required IconData icon,
      required List<Widget> children}) {
    return DecoratedBox(
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surface,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: Theme.of(context).colorScheme.outlineVariant),
      ),
      child: ConstrainedBox(
        constraints: const BoxConstraints(minHeight: 260),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(children: [
                Icon(icon),
                const SizedBox(width: 8),
                Text(title, style: Theme.of(context).textTheme.titleMedium)
              ]),
              const SizedBox(height: 16),
              ...children,
            ],
          ),
        ),
      ),
    );
  }
}

String _basename(String path) {
  final separator = Platform.pathSeparator;
  return path.split(separator).last;
}

String _formatDuration(int seconds) {
  final safe = seconds < 0 ? 0 : seconds;
  final hours = safe ~/ 3600;
  final minutes = (safe % 3600) ~/ 60;
  final secs = safe % 60;
  return '${hours.toString().padLeft(2, '0')}:${minutes.toString().padLeft(2, '0')}:${secs.toString().padLeft(2, '0')}';
}

String _normalizePosition(String input) {
  final value = input.trim();
  if (value.isEmpty) {
    return '';
  }
  if (RegExp(r'^\d+(\.\d+)?$').hasMatch(value)) {
    return _formatDuration(double.parse(value).round());
  }
  final parts = value.split(':');
  if (parts.length == 3 &&
      parts.every((part) => RegExp(r'^\d+$').hasMatch(part))) {
    return '${parts[0].padLeft(2, '0')}:${parts[1].padLeft(2, '0')}:${parts[2].padLeft(2, '0')}';
  }
  return value;
}

int? _parsePositionSeconds(String input) {
  final value = input.trim();
  if (value.isEmpty) {
    return null;
  }
  if (RegExp(r'^\d+(\.\d+)?$').hasMatch(value)) {
    return double.parse(value).round();
  }
  final parts = value.split(':');
  if (parts.length == 2 &&
      parts.every((part) => RegExp(r'^\d+$').hasMatch(part))) {
    return int.parse(parts[0]) * 60 + int.parse(parts[1]);
  }
  if (parts.length == 3 &&
      parts.every((part) => RegExp(r'^\d+$').hasMatch(part))) {
    return int.parse(parts[0]) * 3600 +
        int.parse(parts[1]) * 60 +
        int.parse(parts[2]);
  }
  return null;
}

int? _parsePositionSecondsFromUrl(String input) {
  final uri = Uri.tryParse(input);
  final value = uri?.queryParameters['t'] ?? uri?.queryParameters['start'];
  if (value == null || value.isEmpty) {
    return null;
  }
  return _parsePositionSeconds(
      value.endsWith('s') ? value.substring(0, value.length - 1) : value);
}

String _rangePreview(String startInput, String endInput,
    {int fallbackStart = 0}) {
  final start = _parsePositionSeconds(startInput) ?? fallbackStart;
  final end = _parsePositionSeconds(endInput);
  return 'Queue range ${_formatDuration(start)} -> ${end == null ? 'end' : _formatDuration(end)}';
}

String? _nonEmptyString(Object? value) {
  final text = value?.toString().trim();
  return text == null || text.isEmpty ? null : text;
}

String? _metadataSourceUrl(Map<String, dynamic>? metadata) =>
    _nonEmptyString(metadata?['source_url']);

bool _metadataMatchesUrl(Map<String, dynamic>? metadata, String url) {
  final sourceUrl = _metadataSourceUrl(metadata);
  return sourceUrl != null && sourceUrl == url.trim();
}

@visibleForTesting
PlaybackQueueItem videoQueueItemForTest({
  required String url,
  Map<String, dynamic>? inspectedVideo,
  Map<String, dynamic>? cachedVideo,
  int startSeconds = 0,
  int? endSeconds,
}) {
  final cleanUrl = url.trim();
  final matchingInspection =
      _metadataMatchesUrl(inspectedVideo, cleanUrl) ? inspectedVideo : null;
  final matchingCache =
      _metadataMatchesUrl(cachedVideo, cleanUrl) ? cachedVideo : null;
  final title = _nonEmptyString(matchingInspection?['title']) ??
      _nonEmptyString(matchingCache?['title']) ??
      cleanUrl;
  return PlaybackQueueItem(
    kind: QueueItemKind.video,
    source: cleanUrl,
    title: title,
    startSeconds: startSeconds,
    endSeconds: endSeconds,
    cachedPath: _nonEmptyString(matchingCache?['path']),
    cachedMeta: matchingCache == null
        ? null
        : {
            ...matchingCache,
            'source_url': cleanUrl,
          },
  );
}

@visibleForTesting
int? nextQueueVideoToCacheForTest(
  List<PlaybackQueueItem> queue, {
  required int currentQueueIndex,
  required String? activeDownloadTaskId,
  required int? activeDownloadQueueIndex,
  required bool playAfterDownload,
}) {
  if (playAfterDownload ||
      activeDownloadTaskId != null ||
      activeDownloadQueueIndex != null) {
    return null;
  }
  final start = (currentQueueIndex + 1).clamp(0, queue.length);
  for (var index = start; index < queue.length; index++) {
    final item = queue[index];
    if (item.kind == QueueItemKind.video && !item.isReady) {
      return index;
    }
  }
  return null;
}

@visibleForTesting
int? queueIndexToPlayAfterDownloadForTest({
  required bool queueActive,
  required bool queueAdvancing,
  required int currentQueueIndex,
  required int? completedQueueIndex,
}) {
  if (!queueActive || completedQueueIndex == null) {
    return null;
  }
  if (!queueAdvancing && currentQueueIndex == -1 && completedQueueIndex == 0) {
    return completedQueueIndex;
  }
  if (!queueAdvancing || completedQueueIndex != currentQueueIndex) {
    return null;
  }
  return completedQueueIndex;
}

String _formatPercent(double value) {
  return '${(value * 100).clamp(0, 100).toStringAsFixed(1)}%';
}

String _formatClock(double epochSeconds) {
  final time =
      DateTime.fromMillisecondsSinceEpoch((epochSeconds * 1000).round());
  return '${time.hour.toString().padLeft(2, '0')}:${time.minute.toString().padLeft(2, '0')}:${time.second.toString().padLeft(2, '0')}';
}

double? _recentPlaybackRate(List<StatusSample> samples) {
  if (samples.length < 2) {
    return null;
  }
  final latest = samples.last;
  final previous = samples.reversed.skip(1).firstWhere(
        (sample) => sample.positionSeconds != latest.positionSeconds,
        orElse: () => samples.first,
      );
  final elapsed = latest.time.difference(previous.time).inMilliseconds / 1000.0;
  if (elapsed <= 0) {
    return null;
  }
  final delta = latest.positionSeconds - previous.positionSeconds;
  if (delta < 0) {
    return null;
  }
  return delta / elapsed;
}

String _formatBytes(num? bytes) {
  if (bytes == null || bytes <= 0) {
    return '--';
  }
  const units = ['B', 'KB', 'MB', 'GB'];
  var size = bytes.toDouble();
  var unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit++;
  }
  return '${size.toStringAsFixed(unit == 0 ? 0 : 1)} ${units[unit]}';
}

String _downloadProgressText(Map<String, dynamic> progress) {
  final percent = (progress['percent'] as num?)?.toDouble();
  final downloaded = progress['downloaded_bytes'] as num?;
  final total = progress['total_bytes'] as num?;
  final speed = progress['speed'] as num?;
  final eta = progress['eta'] as num?;
  final fragmentIndex = progress['fragment_index'] as num?;
  final fragmentCount = progress['fragment_count'] as num?;
  final phase = progress['phase']?.toString() ??
      progress['status']?.toString() ??
      'downloading';
  final parts = <String>[phase];
  if (percent != null) {
    parts.add(_formatPercent(percent));
  }
  if (fragmentIndex != null && fragmentCount != null) {
    parts.add('part ${fragmentIndex.round()}/${fragmentCount.round()}');
  }
  if ((downloaded ?? 0) > 0 || (total ?? 0) > 0) {
    parts.add('${_formatBytes(downloaded)} / ${_formatBytes(total)}');
  }
  if (speed != null && speed > 0) {
    parts.add('speed ${_formatBytes(speed)}/s');
  }
  if (eta != null && eta > 0) {
    parts.add('ETA ${_formatDuration(eta.round())}');
  }
  return [
    ...parts,
  ].join('  ');
}

double? _downloadProgressIndicatorValue(Map<String, dynamic> progress) {
  if (progress['estimated'] == true) {
    return null;
  }
  return (progress['percent'] as num?)?.toDouble().clamp(0.0, 1.0);
}

@visibleForTesting
String downloadProgressTextForTest(Map<String, dynamic> progress) =>
    _downloadProgressText(progress);

@visibleForTesting
double? downloadProgressIndicatorValueForTest(Map<String, dynamic> progress) =>
    _downloadProgressIndicatorValue(progress);

@visibleForTesting
int? parsePositionSecondsForTest(String input) => _parsePositionSeconds(input);

@visibleForTesting
int? parsePositionSecondsFromUrlForTest(String input) =>
    _parsePositionSecondsFromUrl(input);

@visibleForTesting
String rangePreviewForTest(String startInput, String endInput,
        {int fallbackStart = 0}) =>
    _rangePreview(startInput, endInput, fallbackStart: fallbackStart);

class StatusChart extends StatelessWidget {
  const StatusChart({required this.samples, super.key});

  final List<StatusSample> samples;

  @override
  Widget build(BuildContext context) {
    final axisColor = Theme.of(context).colorScheme.outline;
    final lineColor = Theme.of(context).colorScheme.primary;
    const progressColor = Colors.cyanAccent;
    return DecoratedBox(
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Padding(
        padding: const EdgeInsets.all(10),
        child: CustomPaint(
          painter: StatusChartPainter(
            samples: samples,
            axisColor: axisColor,
            lineColor: lineColor,
            progressColor: progressColor,
          ),
          child: Align(
            alignment: Alignment.topLeft,
            child: Wrap(
              spacing: 12,
              runSpacing: 4,
              children: [
                _legendSwatch(lineColor, 'Status'),
                _legendSwatch(progressColor, 'Progress'),
                Text(
                    samples.isEmpty ? 'Waiting' : 'Last ${samples.length * 2}s',
                    style: Theme.of(context).textTheme.labelMedium),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _legendSwatch(Color color, String label) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(width: 18, height: 3, color: color),
        const SizedBox(width: 5),
        Text(label),
      ],
    );
  }
}

class StatusChartPainter extends CustomPainter {
  StatusChartPainter({
    required this.samples,
    required this.axisColor,
    required this.lineColor,
    required this.progressColor,
  });

  final List<StatusSample> samples;
  final Color axisColor;
  final Color lineColor;
  final Color progressColor;

  @override
  void paint(Canvas canvas, Size size) {
    final chartRect = Rect.fromLTWH(34, 24, size.width - 62, size.height - 48);
    final axisPaint = Paint()
      ..color = axisColor.withValues(alpha: 0.35)
      ..strokeWidth = 1;
    final labelPainter = TextPainter(textDirection: TextDirection.ltr);
    for (var i = 0; i <= 4; i++) {
      final y = chartRect.top + chartRect.height * i / 4;
      canvas.drawLine(
          Offset(chartRect.left, y), Offset(chartRect.right, y), axisPaint);
      final value = (1 - i / 4).toStringAsFixed(2);
      labelPainter.text = TextSpan(
          text: value, style: TextStyle(color: axisColor, fontSize: 10));
      labelPainter.layout();
      labelPainter.paint(canvas, Offset(2, y - 6));
    }
    canvas.drawLine(Offset(chartRect.left, chartRect.bottom),
        Offset(chartRect.right, chartRect.bottom), axisPaint);
    labelPainter.text =
        TextSpan(text: '0s', style: TextStyle(color: axisColor, fontSize: 10));
    labelPainter.layout();
    labelPainter.paint(canvas, Offset(chartRect.left, chartRect.bottom + 4));
    labelPainter.text =
        TextSpan(text: 'now', style: TextStyle(color: axisColor, fontSize: 10));
    labelPainter.layout();
    labelPainter.paint(canvas,
        Offset(chartRect.right - labelPainter.width, chartRect.bottom + 4));
    if (samples.length < 2) {
      return;
    }

    Path pathFor(double Function(StatusSample sample) valueOf) {
      final path = Path();
      for (var i = 0; i < samples.length; i++) {
        final x = chartRect.left + chartRect.width * i / (samples.length - 1);
        final y = chartRect.bottom -
            chartRect.height * valueOf(samples[i]).clamp(0.0, 1.0);
        if (i == 0) {
          path.moveTo(x, y);
        } else {
          path.lineTo(x, y);
        }
      }
      return path;
    }

    final progressPaint = Paint()
      ..color = progressColor.withValues(alpha: 0.75)
      ..strokeWidth = 2
      ..style = PaintingStyle.stroke;
    final healthPaint = Paint()
      ..color = lineColor
      ..strokeWidth = 3
      ..strokeCap = StrokeCap.round
      ..style = PaintingStyle.stroke;
    canvas.drawPath(pathFor((sample) => sample.progress), progressPaint);
    canvas.drawPath(pathFor((sample) => sample.score), healthPaint);

    final dotPaint = Paint()..style = PaintingStyle.fill;
    for (var i = 0; i < samples.length; i++) {
      final sample = samples[i];
      final x = chartRect.left + chartRect.width * i / (samples.length - 1);
      final y =
          chartRect.bottom - chartRect.height * sample.score.clamp(0.0, 1.0);
      dotPaint.color = switch (sample.state) {
        'PLAYING' => Colors.greenAccent,
        'ERROR' => Colors.redAccent,
        'STOPPED' || 'NO_MEDIA_PRESENT' || 'IDLE' => Colors.orangeAccent,
        _ => lineColor,
      };
      canvas.drawCircle(Offset(x, y), 2.4, dotPaint);
    }
  }

  @override
  bool shouldRepaint(covariant StatusChartPainter oldDelegate) {
    return oldDelegate.samples != samples ||
        oldDelegate.axisColor != axisColor ||
        oldDelegate.lineColor != lineColor ||
        oldDelegate.progressColor != progressColor;
  }
}
