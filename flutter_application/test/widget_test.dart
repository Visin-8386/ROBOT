import 'package:flutter_application/main.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('App loads smoke test', (WidgetTester tester) async {
    await tester.pumpWidget(const RobotApp());
    expect(find.text('Điều khiển'), findsOneWidget);
  });
}
