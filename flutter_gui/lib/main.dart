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
    _process!.stderr.transform(const Utf8Decoder(allowMalformed: true)).listen((line) {
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
        for (final filename in ['gui_bridge.exe', 'auto-cast-bridge.exe', 'gui_bridge.py']) {
          final candidate = File('${cursor.path}${Platform.pathSeparator}$filename');
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
    final bundledPython = File('${exeDir.path}${Platform.pathSeparator}$bundled');
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

  Future<Map<String, dynamic>> send(String command, Map<String, dynamic> body) async {
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
      onEvent?.call(event, (decoded['payload'] as Map? ?? {}).cast<String, dynamic>());
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
      completer.completeError(Exception(decoded['error'] ?? 'Bridge command failed'));
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
  String get type => data['display_type']?.toString() ?? data['device_type']?.toString() ?? '';
  String get ip => data['ip']?.toString() ?? '';
  String get model => data['model']?.toString() ?? '';
  List<String> get capabilities => (data['capabilities'] as List?)?.map((item) => item.toString()).toList() ?? const [];
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
  bool playAfterDownload = false;
  bool seeking = false;
  bool pollingStatus = false;
  bool autoSearchResume = false;
  bool autoResumeBusy = false;
  Timer? bitrateDebounce;

  @override
  void initState() {
    super.initState();
    bridge.onEvent = _handleBridgeEvent;
    unawaited(_refreshSources());
    unawaited(_refreshState());
    statusTimer = Timer.periodic(const Duration(seconds: 2), (_) => unawaited(_pollPlaybackStatus()));
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
    autoSearchTimer = Timer.periodic(const Duration(seconds: 5), (_) => unawaited(_tryAutoResume()));
  }

  Future<void> _tryAutoResume() async {
    if (!autoSearchResume || autoResumeBusy || playbackStatus['playing'] == true) {
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
      setState(() {
        cachedVideo = payload;
        downloadProgress = {
          ...payload,
          'status': 'complete',
          'phase': 'Complete',
          'percent': 1.0,
          'filename': payload['path'],
        };
        activeDownloadTaskId = null;
        status = 'Cached to ${payload['path']}';
      });
      if (playAfterDownload) {
        playAfterDownload = false;
        unawaited(_playCachedVideo(payload));
      }
    } else if (event == 'download_failed') {
      setState(() {
        activeDownloadTaskId = null;
        playAfterDownload = false;
        downloadProgress = null;
        status = '${payload['status']}: ${payload['error']}';
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
    } catch (error) {
      if (mounted) {
        setState(() => playbackStatus = {
              ...playbackStatus,
              'state': 'ERROR',
              'status': error.toString(),
            });
      }
    }
    finally {
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
          ..addAll((windowResult['windows'] as List? ?? []).map((item) => (item as Map).cast<String, dynamic>()));
        monitors
          ..clear()
          ..addAll((monitorResult['monitors'] as List? ?? []).map((item) => (item as Map).cast<String, dynamic>()));
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

  Future<void> _playFile() async {
    final device = selectedDevice;
    final path = selectedFile;
    if (device == null || path == null) {
      setState(() => status = 'Select a device and media file first');
      return;
    }
    await _run('Starting media playback...', () async {
      final position = _normalizePosition(mediaStartController.text);
      await bridge.send('play_media', {'device': device.data, 'path': path, 'position': position});
      final suffix = position.isEmpty ? '' : ' from $position';
      setState(() => status = 'Playing ${_basename(path)} on ${device.name}$suffix');
      unawaited(_pollPlaybackStatus());
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
        inspectedVideo = result;
        cachedVideo = null;
        status = '${result['title']}  ${result['duration_string'] ?? ''}';
      });
    });
  }

  Future<void> _cacheAndPlayVideo() async {
    final device = selectedDevice;
    final url = videoController.text.trim();
    if (device == null || url.isEmpty) {
      setState(() => status = 'Select a device and enter a video URL first');
      return;
    }
    await _run('Starting cache task...', () async {
      setState(() => downloadProgress = {'status': 'starting', 'percent': 0.0});
      final started = await bridge.send('cache_video', {'url': url});
      setState(() {
        activeDownloadTaskId = started['task_id']?.toString();
        playAfterDownload = true;
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

  Future<void> _cancelCache() async {
    final taskId = activeDownloadTaskId;
    if (taskId == null) {
      return;
    }
    await bridge.send('cancel_cache', {'task_id': taskId});
    setState(() {
      status = 'Cancelling download...';
      playAfterDownload = false;
    });
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
    final monitor = monitors[selectedMonitorIndex.clamp(0, monitors.length - 1).toInt()];
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
    final device = selectedDevice;
    if (device == null) {
      return;
    }
    try {
      await bridge.send('set_volume', {'device': device.data, 'volume': value.round()});
    } catch (error) {
      setState(() => status = error.toString());
    }
  }

  void _setBitrate(double value) {
    setState(() => bitrate = value);
    bitrateDebounce?.cancel();
    bitrateDebounce = Timer(const Duration(milliseconds: 900), () => unawaited(_applyBitrateRestart()));
  }

  Future<void> _applyBitrateRestart() async {
    if (playbackStatus['playing'] != true) {
      return;
    }
    final sourceType = playbackStatus['source_type']?.toString() ?? '';
    if (!{'live', 'window', 'screen'}.contains(sourceType)) {
      setState(() => status = 'Bitrate applies to live/window/screen streams');
      return;
    }
    try {
      setState(() => status = 'Restarting stream at ${bitrate.round()}k...');
      final result = await bridge.send('restart_stream', {'video_bitrate': '${bitrate.round()}k'});
      setState(() => status = result['status'] == 'skipped' ? result['reason'].toString() : 'Stream restarted at ${bitrate.round()}k');
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
            icon: busy ? const SizedBox.square(dimension: 18, child: CircularProgressIndicator(strokeWidth: 2)) : const Icon(Icons.radar),
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
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                  tileColor: selected ? Theme.of(context).colorScheme.primaryContainer : Theme.of(context).colorScheme.surfaceContainerHighest,
                  leading: const Icon(Icons.tv),
                  title: Text(device.name, maxLines: 1, overflow: TextOverflow.ellipsis),
                  subtitle: Text(device.subtitle, maxLines: 1, overflow: TextOverflow.ellipsis),
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
            _activeModePanel(),
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
        final cardWidth = constraints.maxWidth < 760 ? (constraints.maxWidth - 12) / 2 : (constraints.maxWidth - 36) / 4;
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
          color: selected ? Theme.of(context).colorScheme.primaryContainer : Theme.of(context).colorScheme.surface,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: selected ? Theme.of(context).colorScheme.primary : Theme.of(context).colorScheme.outlineVariant),
        ),
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Row(
            children: [
              Icon(mode.icon),
              const SizedBox(width: 10),
              Expanded(child: Text(mode.label, maxLines: 1, overflow: TextOverflow.ellipsis)),
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
            Expanded(child: Text(status, maxLines: 2, overflow: TextOverflow.ellipsis)),
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
    final positionSeconds = (playbackStatus['position_seconds'] as num?)?.toDouble() ?? 0;
    final durationSeconds = (playbackStatus['duration_seconds'] as num?)?.toDouble() ?? 0;
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
                      Icon(playing ? Icons.cast_connected : Icons.cast, color: statusColor),
                      const SizedBox(width: 8),
                      Expanded(child: Text(state, style: Theme.of(context).textTheme.titleMedium)),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Text(detail.isEmpty ? 'Waiting for playback status' : detail, maxLines: 2, overflow: TextOverflow.ellipsis),
                  const SizedBox(height: 8),
                  Text('Source ${sourceType.isEmpty ? '--' : sourceType}'),
                  Text('Pos ${position.isEmpty ? '--' : position}/${duration.isEmpty ? '--' : duration}'),
                  Text('Vol ${volumeValue == null ? '--' : '$volumeValue%'}'),
                  Text('TV latency ${showTvMetrics && latencyMs != null ? '${latencyMs}ms' : '--'}'),
                  Text('Last check ${showTvMetrics && checkedAt != null ? _formatClock(checkedAt) : '--'}'),
                  Text('Rate ${showTvMetrics && playRate != null ? '${playRate.toStringAsFixed(2)}x' : '--'}'),
                  if (durationSeconds > 0)
                    Slider(
                      value: positionSeconds.clamp(0, durationSeconds),
                      min: 0,
                      max: durationSeconds,
                      divisions: durationSeconds > 0 ? durationSeconds.round().clamp(1, 1000) : null,
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
    return _panel(
      title: 'Media File',
      icon: Icons.video_file,
      children: [
        OutlinedButton.icon(onPressed: busy ? null : _pickFile, icon: const Icon(Icons.folder_open), label: const Text('Choose File')),
        const SizedBox(height: 10),
        Text(selectedFile == null ? 'No file selected' : _basename(selectedFile!), maxLines: 2, overflow: TextOverflow.ellipsis),
        const SizedBox(height: 10),
        TextField(
          controller: mediaStartController,
          decoration: const InputDecoration(labelText: 'Start time, e.g. 01:01:09 or 3669', border: OutlineInputBorder()),
        ),
        const SizedBox(height: 14),
        FilledButton.icon(onPressed: busy ? null : _playFile, icon: const Icon(Icons.play_arrow), label: const Text('Play File')),
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
          decoration: const InputDecoration(labelText: 'Live URL', border: OutlineInputBorder()),
        ),
        const SizedBox(height: 24),
        FilledButton.icon(onPressed: busy ? null : _playLive, icon: const Icon(Icons.cast), label: const Text('Play Live')),
      ],
    );
  }

  Widget _videoUrlControls() {
    final video = inspectedVideo;
    final title = video?['title']?.toString();
    final duration = video?['duration_string']?.toString();
    final start = video?['start_time']?.toString();
    final progress = downloadProgress;
    final percent = (progress?['percent'] as num?)?.toDouble();
    final path = cachedVideo?['path']?.toString() ?? progress?['filename']?.toString();
    return _panel(
      title: 'Video URL',
      icon: Icons.ondemand_video,
      children: [
        TextField(
          controller: videoController,
          decoration: const InputDecoration(labelText: 'Bilibili or video page URL', border: OutlineInputBorder()),
        ),
        const SizedBox(height: 10),
        OutlinedButton.icon(onPressed: busy ? null : _inspectVideo, icon: const Icon(Icons.info_outline), label: const Text('Inspect')),
        const SizedBox(height: 10),
        if (title != null) Text(title, maxLines: 2, overflow: TextOverflow.ellipsis),
        if (duration != null) Text('Duration $duration  Start ${start ?? '0'}s'),
        const SizedBox(height: 8),
        Text('Cache folder ${cacheDir.isEmpty ? '--' : cacheDir}', maxLines: 1, overflow: TextOverflow.ellipsis),
        if (path != null && path.isNotEmpty) Text('File $path', maxLines: 2, overflow: TextOverflow.ellipsis),
        if (progress != null) ...[
          const SizedBox(height: 8),
          LinearProgressIndicator(value: percent?.clamp(0.0, 1.0)),
          const SizedBox(height: 6),
          Text(_downloadProgressText(progress)),
          if (activeDownloadTaskId != null) ...[
            const SizedBox(height: 8),
            OutlinedButton.icon(onPressed: busy ? null : _cancelCache, icon: const Icon(Icons.cancel), label: const Text('Cancel Download')),
          ],
        ],
        const SizedBox(height: 14),
        FilledButton.icon(onPressed: busy ? null : _cacheAndPlayVideo, icon: const Icon(Icons.download_for_offline), label: const Text('Cache & Play')),
      ],
    );
  }

  Widget _captureControls() {
    return _panel(
      title: 'Capture',
      icon: Icons.screenshot_monitor,
      children: [
        OutlinedButton.icon(onPressed: busy ? null : _refreshSources, icon: const Icon(Icons.refresh), label: const Text('Refresh Sources')),
        const SizedBox(height: 10),
        DropdownButtonFormField<int>(
          initialValue: selectedWindowIndex,
          decoration: const InputDecoration(labelText: 'Window', border: OutlineInputBorder()),
          items: [
            for (var i = 0; i < windows.length; i++)
              DropdownMenuItem(value: i, child: Text(windows[i]['title']?.toString() ?? 'Window $i', overflow: TextOverflow.ellipsis)),
          ],
          onChanged: (value) => setState(() => selectedWindowIndex = value),
        ),
        const SizedBox(height: 10),
        FilledButton.tonalIcon(onPressed: busy ? null : _castWindow, icon: const Icon(Icons.web_asset), label: const Text('Cast Window')),
        const SizedBox(height: 14),
        DropdownButtonFormField<int>(
          initialValue: monitors.isEmpty ? null : selectedMonitorIndex,
          decoration: const InputDecoration(labelText: 'Monitor', border: OutlineInputBorder()),
          items: [
            for (var i = 0; i < monitors.length; i++)
              DropdownMenuItem(value: i, child: Text(monitors[i]['name']?.toString() ?? 'Monitor $i')),
          ],
          onChanged: (value) => setState(() => selectedMonitorIndex = value ?? 0),
        ),
        const SizedBox(height: 10),
        FilledButton.icon(onPressed: busy ? null : _castScreen, icon: const Icon(Icons.desktop_windows), label: const Text('Cast Screen')),
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
            _sliderRow(Icons.volume_up, Slider(value: volume, min: 0, max: 100, divisions: 20, label: '${volume.round()}%', onChanged: _setVolume), '${volume.round()}%'),
            _sliderRow(Icons.speed, Slider(value: bitrate, min: 1000, max: 8000, divisions: 14, label: '${bitrate.round()}k', onChanged: _setBitrate), '${bitrate.round()}k'),
            _sliderRow(Icons.motion_photos_on, Slider(value: fps, min: 5, max: 30, divisions: 5, label: '${fps.round()} fps', onChanged: (value) => setState(() => fps = value)), '${fps.round()} fps'),
          ];
          return Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
            child: constraints.maxWidth < 820
                ? Column(children: rows)
                : Row(children: rows.map((row) => Expanded(child: row)).toList()),
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

  Widget _panel({required String title, required IconData icon, required List<Widget> children}) {
    return DecoratedBox(
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surface,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: Theme.of(context).colorScheme.outlineVariant),
      ),
      child: ConstrainedBox(
        constraints: const BoxConstraints(minHeight: 300),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(children: [Icon(icon), const SizedBox(width: 8), Text(title, style: Theme.of(context).textTheme.titleMedium)]),
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
  if (parts.length == 3 && parts.every((part) => RegExp(r'^\d+$').hasMatch(part))) {
    return '${parts[0].padLeft(2, '0')}:${parts[1].padLeft(2, '0')}:${parts[2].padLeft(2, '0')}';
  }
  return value;
}

String _formatPercent(double value) {
  return '${(value * 100).clamp(0, 100).toStringAsFixed(1)}%';
}

String _formatClock(double epochSeconds) {
  final time = DateTime.fromMillisecondsSinceEpoch((epochSeconds * 1000).round());
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
  final phase = progress['phase']?.toString() ?? progress['status']?.toString() ?? 'downloading';
  final parts = <String>[phase];
  if (percent != null) {
    parts.add(_formatPercent(percent));
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

@visibleForTesting
String downloadProgressTextForTest(Map<String, dynamic> progress) => _downloadProgressText(progress);

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
                Text(samples.isEmpty ? 'Waiting' : 'Last ${samples.length * 2}s', style: Theme.of(context).textTheme.labelMedium),
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
      canvas.drawLine(Offset(chartRect.left, y), Offset(chartRect.right, y), axisPaint);
      final value = (1 - i / 4).toStringAsFixed(2);
      labelPainter.text = TextSpan(text: value, style: TextStyle(color: axisColor, fontSize: 10));
      labelPainter.layout();
      labelPainter.paint(canvas, Offset(2, y - 6));
    }
    canvas.drawLine(Offset(chartRect.left, chartRect.bottom), Offset(chartRect.right, chartRect.bottom), axisPaint);
    labelPainter.text = TextSpan(text: '0s', style: TextStyle(color: axisColor, fontSize: 10));
    labelPainter.layout();
    labelPainter.paint(canvas, Offset(chartRect.left, chartRect.bottom + 4));
    labelPainter.text = TextSpan(text: 'now', style: TextStyle(color: axisColor, fontSize: 10));
    labelPainter.layout();
    labelPainter.paint(canvas, Offset(chartRect.right - labelPainter.width, chartRect.bottom + 4));
    if (samples.length < 2) {
      return;
    }

    Path pathFor(double Function(StatusSample sample) valueOf) {
      final path = Path();
      for (var i = 0; i < samples.length; i++) {
        final x = chartRect.left + chartRect.width * i / (samples.length - 1);
        final y = chartRect.bottom - chartRect.height * valueOf(samples[i]).clamp(0.0, 1.0);
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
      final y = chartRect.bottom - chartRect.height * sample.score.clamp(0.0, 1.0);
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
