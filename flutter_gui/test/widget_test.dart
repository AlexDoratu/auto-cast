import 'package:auto_cast_flutter/main.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('renders Auto-Cast shell', (tester) async {
    await tester.pumpWidget(const AutoCastApp());
    expect(find.text('Auto-Cast'), findsOneWidget);
    expect(find.text('Scan Devices'), findsOneWidget);
    expect(find.textContaining('TV clock'), findsNothing);
    expect(find.textContaining('Last check'), findsOneWidget);
  });

  test('bridge ignores non-json process output', () {
    final bridge = AutoCastBridge();
    addTearDown(bridge.dispose);

    bridge.handleLineForTest('native warning \ufffd without json');
    expect(bridge.status.value, 'native warning \ufffd without json');
  });

  test('download progress text shows phase and completed percent', () {
    expect(
      downloadProgressTextForTest({
        'phase': 'Complete',
        'percent': 1.0,
        'downloaded_bytes': 1024,
        'total_bytes': 1024,
      }),
      contains('Complete  100.0%'),
    );
  });

  test('download progress text shows fragment count', () {
    final text = downloadProgressTextForTest({
      'phase': 'Downloading video',
      'percent': 0.3,
      'fragment_index': 3,
      'fragment_count': 10,
    });
    expect(text, contains('30.0%'));
    expect(text, contains('part 3/10'));
  });

  test('estimated download progress uses indeterminate indicator', () {
    expect(
      downloadProgressIndicatorValueForTest({
        'phase': 'Resolving video',
        'percent': 0.02,
        'estimated': true,
      }),
      isNull,
    );
    expect(
      downloadProgressIndicatorValueForTest({
        'phase': 'Downloading video',
        'percent': 0.3,
        'downloaded_bytes': 30,
        'total_bytes': 100,
      }),
      0.3,
    );
  });

  test('queue time parser accepts seconds and clock formats', () {
    expect(parsePositionSecondsForTest('3669'), 3669);
    expect(parsePositionSecondsForTest('61:09'), 3669);
    expect(parsePositionSecondsForTest('01:01:09'), 3669);
    expect(parsePositionSecondsForTest('bad'), isNull);
  });

  test('queue time parser reads bilibili t parameter', () {
    expect(
      parsePositionSecondsFromUrlForTest(
          'https://www.bilibili.com/video/BV1euUWB5Eg4/?t=3669'),
      3669,
    );
  });

  test('queue range preview uses fallback start', () {
    expect(
      rangePreviewForTest('', '01:02', fallbackStart: 30),
      'Queue range 00:00:30 -> 00:01:02',
    );
  });

  test('video queue item ignores cached metadata from a different URL', () {
    final item = videoQueueItemForTest(
      url: 'https://example.com/p9',
      inspectedVideo: {
        'source_url': 'https://example.com/p8',
        'title': 'p8',
      },
      cachedVideo: {
        'source_url': 'https://example.com/p8',
        'title': 'p8',
        'path': 'D:/cache/p8.mp4',
      },
    );

    expect(item.source, 'https://example.com/p9');
    expect(item.title, 'https://example.com/p9');
    expect(item.cachedPath, isNull);
    expect(item.isReady, isFalse);
  });

  test('queue prefetch chooses the next uncached video after current item', () {
    final queue = [
      PlaybackQueueItem(
        kind: QueueItemKind.media,
        source: 'D:/video/p8.mp4',
        title: 'p8',
      ),
      PlaybackQueueItem(
        kind: QueueItemKind.video,
        source: 'https://example.com/p9',
        title: 'p9',
      ),
    ];

    expect(
      nextQueueVideoToCacheForTest(
        queue,
        currentQueueIndex: 0,
        activeDownloadTaskId: null,
        activeDownloadQueueIndex: null,
        playAfterDownload: false,
      ),
      1,
    );
  });

  test('future queue download completion does not replay current item', () {
    expect(
      queueIndexToPlayAfterDownloadForTest(
        queueActive: true,
        queueAdvancing: false,
        currentQueueIndex: 0,
        completedQueueIndex: 1,
      ),
      isNull,
    );
    expect(
      queueIndexToPlayAfterDownloadForTest(
        queueActive: true,
        queueAdvancing: true,
        currentQueueIndex: 1,
        completedQueueIndex: 1,
      ),
      1,
    );
  });

  test('first queue download completion starts queue playback', () {
    expect(
      queueIndexToPlayAfterDownloadForTest(
        queueActive: true,
        queueAdvancing: false,
        currentQueueIndex: -1,
        completedQueueIndex: 0,
      ),
      0,
    );
  });
}
