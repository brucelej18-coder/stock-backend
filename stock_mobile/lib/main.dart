import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:intl/intl.dart';

// 고정 서버 엔드포인트
const String kBackendUrl = "https://stock-backend-vkfv.onrender.com";

void main() {
  runApp(const StockWatchtowerApp());
}

class StockWatchtowerApp extends StatelessWidget {
  const StockWatchtowerApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Stock Watchtower',
      debugShowCheckedModeBanner: false,
      theme: ThemeData.dark().copyWith(
        scaffoldBackgroundColor: const Color(0xFF0F172A),
        cardColor: const Color(0xFF1E293B),
        colorScheme: const ColorScheme.dark(
          primary: Color(0xFF38BDF8),
          secondary: Color(0xFF818CF8),
        ),
      ),
      home: const StockWatchtowerScreen(),
    );
  }
}

// 1. 뉴스 데이터 모델
class NewsItem {
  final String title;
  final String publisher;
  final String link;

  NewsItem({required this.title, required this.publisher, required this.link});

  factory NewsItem.fromJson(Map<String, dynamic> json) {
    return NewsItem(
      title: json['title'] ?? '',
      publisher: json['publisher'] ?? '',
      link: json['link'] ?? '',
    );
  }
}

// 2. 통합 주식 및 AI 전략 데이터 모델
class Stock {
  final String ticker;
  final bool isHolding;
  final double? avgPrice;
  final double quantity;
  final double currentPrice;
  final int aiScore;
  final double rsi;
  final double macd;
  final double ma5;
  final double ma20;
  final double ma60;
  final double targetSell;
  final double targetBuy;
  final double stopLoss;
  final double profitRate;
  final int profitKrw;
  final List<NewsItem> news;

  Stock({
    required this.ticker,
    required this.isHolding,
    this.avgPrice,
    required this.quantity,
    required this.currentPrice,
    required this.aiScore,
    required this.rsi,
    required this.macd,
    required this.ma5,
    required this.ma20,
    required this.ma60,
    required this.targetSell,
    required this.targetBuy,
    required this.stopLoss,
    required this.profitRate,
    required this.profitKrw,
    required this.news,
  });

  factory Stock.fromJson(Map<String, dynamic> json) {
    var rawNews = json['news'] as List? ?? [];
    List<NewsItem> parsedNews =
        rawNews.map((n) => NewsItem.fromJson(Map<String, dynamic>.from(n))).toList();

    return Stock(
      ticker: json['ticker'] ?? '',
      isHolding: json['is_holding'] ?? false,
      avgPrice: json['avg_price'] != null ? (json['avg_price'] as num).toDouble() : null,
      quantity: (json['quantity'] as num?)?.toDouble() ?? 0.0,
      currentPrice: (json['current_price'] as num?)?.toDouble() ?? 0.0,
      aiScore: json['ai_score'] ?? 50,
      rsi: (json['rsi'] as num?)?.toDouble() ?? 50.0,
      macd: (json['macd'] as num?)?.toDouble() ?? 0.0,
      ma5: (json['ma5'] as num?)?.toDouble() ?? 0.0,
      ma20: (json['ma20'] as num?)?.toDouble() ?? 0.0,
      ma60: (json['ma60'] as num?)?.toDouble() ?? 0.0,
      targetSell: (json['target_sell'] as num?)?.toDouble() ?? 0.0,
      targetBuy: (json['target_buy'] as num?)?.toDouble() ?? 0.0,
      stopLoss: (json['stop_loss'] as num?)?.toDouble() ?? 0.0,
      profitRate: (json['profit_rate'] as num?)?.toDouble() ?? 0.0,
      profitKrw: json['profit_krw'] ?? 0,
      news: parsedNews,
    );
  }
}

// 3. 메인 관제탑 스크린
class StockWatchtowerScreen extends StatefulWidget {
  const StockWatchtowerScreen({super.key});

  @override
  State<StockWatchtowerScreen> createState() => _StockWatchtowerScreenState();
}

class _StockWatchtowerScreenState extends State<StockWatchtowerScreen> {
  List<Stock> _stocks = [];
  bool _isLoading = true;
  String _errorMessage = '';

  final NumberFormat _currencyFormat = NumberFormat("#,##0", "ko_KR");

  @override
  void initState() {
    super.initState();
    fetchStocks();
  }

  // 실시간 주식 및 AI 전략 데이터 호출
  Future<void> fetchStocks() async {
    setState(() {
      _isLoading = true;
      _errorMessage = '';
    });

    try {
      final response = await http.get(Uri.parse('$kBackendUrl/api/stocks'));
      if (response.statusCode == 200) {
        final List<dynamic> data = json.decode(utf8.decode(response.bodyBytes));
        setState(() {
          _stocks = data.map((jsonItem) => Stock.fromJson(jsonItem)).toList();
          _isLoading = false;
        });
      } else {
        setState(() {
          _errorMessage = '서버 응답 오류: ${response.statusCode}';
          _isLoading = false;
        });
      }
    } catch (e) {
      setState(() {
        _errorMessage = '서버 연결 실패: 인터넷 연결 및 서버 상태를 확인해주세요.';
        _isLoading = false;
      });
    }
  }

  // 종목 삭제
  Future<void> deleteStock(String ticker) async {
    try {
      final response = await http.delete(Uri.parse('$kBackendUrl/api/stocks/$ticker'));
      if (response.statusCode == 200) {
        fetchStocks();
      }
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('$ticker 삭제 중 오류가 발생했습니다.')),
      );
    }
  }

  // 종목 추가 다이얼로그
  void _showAddStockDialog() {
    final tickerController = TextEditingController();
    final avgPriceController = TextEditingController();
    final quantityController = TextEditingController();
    bool isHolding = true;

    showDialog(
      context: context,
      builder: (context) {
        return StatefulBuilder(
          builder: (context, setDialogState) {
            return AlertDialog(
              backgroundColor: const Color(0xFF1E293B),
              title: const Text('새 관심/보유 종목 추가', style: TextStyle(color: Colors.white)),
              content: SingleChildScrollView(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    TextField(
                      controller: tickerController,
                      decoration: const InputDecoration(
                        labelText: '티커 (예: NVDA, TSLA)',
                        labelStyle: TextStyle(color: Colors.white70),
                      ),
                      textCapitalization: TextCapitalization.characters,
                    ),
                    SwitchListTile(
                      contentPadding: EdgeInsets.zero,
                      title: const Text('현재 보유 중', style: TextStyle(color: Colors.white)),
                      value: isHolding,
                      onChanged: (val) {
                        setDialogState(() => isHolding = val);
                      },
                    ),
                    if (isHolding) ...[
                      TextField(
                        controller: avgPriceController,
                        keyboardType: const TextInputType.numberWithOptions(decimal: true),
                        decoration: const InputDecoration(
                          labelText: '매수 평단가 (\$)',
                          labelStyle: TextStyle(color: Colors.white70),
                        ),
                      ),
                      TextField(
                        controller: quantityController,
                        keyboardType: const TextInputType.numberWithOptions(decimal: true),
                        decoration: const InputDecoration(
                          labelText: '보유 수량',
                          labelStyle: TextStyle(color: Colors.white70),
                        ),
                      ),
                    ],
                  ],
                ),
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(context),
                  child: const Text('취소', style: TextStyle(color: Colors.white54)),
                ),
                ElevatedButton(
                  onPressed: () async {
                    final ticker = tickerController.text.trim().toUpperCase();
                    if (ticker.isEmpty) return;

                    final double? avgPrice = isHolding ? double.tryParse(avgPriceController.text) : null;
                    final double quantity = isHolding ? (double.tryParse(quantityController.text) ?? 0.0) : 0.0;

                    Navigator.pop(context);
                    await http.post(
                      Uri.parse('$kBackendUrl/api/stocks'),
                      headers: {'Content-Type': 'application/json'},
                      body: json.encode({
                        'ticker': ticker,
                        'is_holding': isHolding,
                        'avg_price': avgPrice,
                        'quantity': quantity,
                      }),
                    );
                    fetchStocks();
                  },
                  child: const Text('등록'),
                ),
              ],
            );
          },
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        backgroundColor: const Color(0xFF0F172A),
        elevation: 0,
        title: const Row(
          children: [
            Icon(Icons.radar, color: Color(0xFF38BDF8)),
            SizedBox(width: 8),
            Text('Stock Watchtower', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 18)),
          ],
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: fetchStocks,
          ),
        ],
      ),
      body: _buildBody(),
      floatingActionButton: FloatingActionButton(
        backgroundColor: const Color(0xFF38BDF8),
        onPressed: _showAddStockDialog,
        child: const Icon(Icons.add, color: Colors.black),
      ),
    );
  }

  Widget _buildBody() {
    if (_isLoading) {
      return const Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            CircularProgressIndicator(color: Color(0xFF38BDF8)),
            SizedBox(height: 16),
            Text('AI 전략 및 실시간 시세 연산 중...', style: TextStyle(color: Colors.white70)),
          ],
        ),
      );
    }

    if (_errorMessage.isNotEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(20.0),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const Icon(Icons.error_outline, color: Colors.redAccent, size: 48),
              const SizedBox(height: 16),
              Text(_errorMessage, textAlign: TextAlign.center, style: const TextStyle(color: Colors.white70)),
              const SizedBox(height: 16),
              ElevatedButton(onPressed: fetchStocks, child: const Text('다시 시도')),
            ],
          ),
        ),
      );
    }

    return RefreshIndicator(
      onRefresh: fetchStocks,
      child: ListView.builder(
        padding: const EdgeInsets.only(left: 14, right: 14, top: 10, bottom: 80),
        itemCount: _stocks.length,
        itemBuilder: (context, index) {
          final stock = _stocks[index];
          return _buildStockCard(stock);
        },
      ),
    );
  }

  // 통합 종목 카드 위젯
  Widget _buildStockCard(Stock stock) {
    final isProfit = stock.profitRate >= 0;
    final profitColor = isProfit ? const Color(0xFFEF4444) : const Color(0xFF3B82F6); // 한국식: 빨강 수익 / 파랑 손실

    return Card(
      margin: const EdgeInsets.only(bottom: 16),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      elevation: 4,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // 상단: 티커, 현재가, AI 점수, 삭제 버튼
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Row(
                  children: [
                    Text(
                      stock.ticker,
                      style: const TextStyle(fontSize: 22, fontWeight: FontWeight.bold, color: Colors.white),
                    ),
                    const SizedBox(width: 8),
                    _buildAiScoreBadge(stock.aiScore),
                  ],
                ),
                Row(
                  children: [
                    Column(
                      crossAxisAlignment: CrossAxisAlignment.end,
                      children: [
                        Text(
                          '\$${stock.currentPrice.toStringAsFixed(2)}',
                          style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: Colors.white),
                        ),
                        if (stock.isHolding && stock.avgPrice != null)
                          Text(
                            '${isProfit ? "+" : ""}${stock.profitRate.toStringAsFixed(2)}% (${_currencyFormat.format(stock.profitKrw)}원)',
                            style: TextStyle(color: profitColor, fontSize: 12, fontWeight: FontWeight.bold),
                          ),
                      ],
                    ),
                    IconButton(
                      icon: const Icon(Icons.close, size: 18, color: Colors.white38),
                      onPressed: () => deleteStock(stock.ticker),
                    ),
                  ],
                ),
              ],
            ),

            if (stock.isHolding && stock.avgPrice != null) ...[
              const SizedBox(height: 6),
              Text(
                '내 평단가: \$${stock.avgPrice!.toStringAsFixed(2)}  |  보유: ${stock.quantity}주',
                style: const TextStyle(color: Colors.white54, fontSize: 12),
              ),
            ],

            const SizedBox(height: 14),

            // [핵심] AI 3단 가격 전략 박스 (익절가 / 추천 매수가 / 손절가)
            Container(
              padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 8),
              decoration: BoxDecoration(
                color: const Color(0xFF0F172A),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: Colors.white12),
              ),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceAround,
                children: [
                  _buildStrategyColumn("AI 목표 익절", "\$${stock.targetSell.toStringAsFixed(2)}", const Color(0xFFF87171)),
                  Container(width: 1, height: 32, color: Colors.white12),
                  _buildStrategyColumn("AI 추천 매수", "\$${stock.targetBuy.toStringAsFixed(2)}", const Color(0xFF34D399)),
                  Container(width: 1, height: 32, color: Colors.white12),
                  _buildStrategyColumn("AI 손절 방어", "\$${stock.stopLoss.toStringAsFixed(2)}", const Color(0xFF60A5FA)),
                ],
              ),
            ),

            const SizedBox(height: 10),

            // 보조 지표 현황 (RSI / MACD / MA20)
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text("RSI: ${stock.rsi.toStringAsFixed(1)}", style: const TextStyle(color: Colors.white60, fontSize: 11)),
                Text("MACD: ${stock.macd.toStringAsFixed(2)}", style: const TextStyle(color: Colors.white60, fontSize: 11)),
                Text("20일선: \$${stock.ma20.toStringAsFixed(2)}", style: const TextStyle(color: Colors.white60, fontSize: 11)),
              ],
            ),

            // [핵심] 실시간 AI 뉴스 헤드라인 섹션
            if (stock.news.isNotEmpty) ...[
              const SizedBox(height: 12),
              const Divider(color: Colors.white12),
              const SizedBox(height: 4),
              const Row(
                children: [
                  Icon(Icons.bolt, color: Colors.amber, size: 16),
                  SizedBox(width: 4),
                  Text("실시간 AI 주요 속보", style: TextStyle(color: Colors.amber, fontSize: 12, fontWeight: FontWeight.bold)),
                ],
              ),
              const SizedBox(height: 6),
              ...stock.news.take(2).map((news) => Padding(
                    padding: const EdgeInsets.only(bottom: 6),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text("• ", style: TextStyle(color: Colors.white54, fontSize: 12)),
                        Expanded(
                          child: Text(
                            news.title,
                            style: const TextStyle(color: Colors.white70, fontSize: 12, height: 1.3),
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                      ],
                    ),
                  )),
            ],
          ],
        ),
      ),
    );
  }

  // AI 점수 배지
  Widget _buildAiScoreBadge(int score) {
    Color badgeColor;
    if (score >= 75) {
      badgeColor = const Color(0xFF10B981); // 강력 매수/호전 (초록)
    } else if (score >= 55) {
      badgeColor = const Color(0xFF38BDF8); // 중립/상승 (파랑)
    } else {
      badgeColor = const Color(0xFFF59E0B); // 주의/하방 (주황)
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: badgeColor.withOpacity(0.2),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: badgeColor, width: 1),
      ),
      child: Text(
        "AI $score점",
        style: TextStyle(color: badgeColor, fontSize: 11, fontWeight: FontWeight.bold),
      ),
    );
  }

  // 전략 컬럼 위젯
  Widget _buildStrategyColumn(String title, String price, Color color) {
    return Column(
      children: [
        Text(title, style: TextStyle(color: color, fontSize: 11, fontWeight: FontWeight.w600)),
        const SizedBox(height: 4),
        Text(price, style: const TextStyle(color: Colors.white, fontSize: 15, fontWeight: FontWeight.bold)),
      ],
    );
  }
}