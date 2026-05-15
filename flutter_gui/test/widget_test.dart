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
}
