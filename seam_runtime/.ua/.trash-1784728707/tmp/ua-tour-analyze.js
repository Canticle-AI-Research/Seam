const fs = require('fs');
const path = require('path');

function main() {
    const inputPath = process.argv[2];
    const outputPath = process.argv[3];

    if (!inputPath || !outputPath) {
        console.error("Usage: node ua-tour-analyze.js <input-path> <output-path>");
        process.exit(1);
    }

    let data;
    try {
        data = JSON.parse(fs.readFileSync(inputPath, 'utf8'));
    } catch (e) {
        console.error("Failed to read input JSON:", e.message);
        process.exit(1);
    }

    const { nodes, edges, layers } = data;

    const nodeMap = {};
    for (const node of nodes) {
        nodeMap[node.id] = node;
    }

    const fanIn = {};
    const fanOut = {};
    const adjacency = {};
    for (const node of nodes) {
        fanIn[node.id] = 0;
        fanOut[node.id] = 0;
        adjacency[node.id] = [];
    }

    for (const edge of edges) {
        const { source, target } = edge;
        if (nodeMap[source] && nodeMap[target]) {
            fanOut[source] = (fanOut[source] || 0) + 1;
            fanIn[target] = (fanIn[target] || 0) + 1;
            adjacency[source].push(target);
        }
    }

    const fanInRanking = nodes.map(n => ({
        id: n.id,
        fanIn: fanIn[n.id],
        name: n.name
    })).sort((a, b) => b.fanIn - a.fanIn).slice(0, 20);

    const fanOutRanking = nodes.map(n => ({
        id: n.id,
        fanOut: fanOut[n.id],
        name: n.name
    })).sort((a, b) => b.fanOut - a.fanOut).slice(0, 20);

    const codeFiles = nodes.filter(n => n.type === 'file');
    const sortedCodeFanOut = codeFiles.map(n => fanOut[n.id]).sort((a, b) => b - a);
    const sortedCodeFanIn = codeFiles.map(n => fanIn[n.id]).sort((a, b) => a - b);

    const top10PercentFanOutThreshold = sortedCodeFanOut[Math.floor(codeFiles.length * 0.1)] || 0;
    const bottom25PercentFanInThreshold = sortedCodeFanIn[Math.floor(codeFiles.length * 0.25)] || 0;

    const entryPointCandidates = [];
    const entryPointNames = new Set([
        'index.ts', 'index.js', 'main.ts', 'main.js', 'app.ts', 'app.js', 'server.ts', 'server.js',
        'mod.rs', 'main.go', 'main.py', 'main.rs', 'manage.py', 'app.py', 'wsgi.py', 'asgi.py',
        'run.py', '__main__.py', 'Application.java', 'Main.java', 'Program.cs', 'config.ru',
        'index.php', 'App.swift', 'Application.kt', 'main.cpp', 'main.c'
    ]);

    for (const node of nodes) {
        let score = 0;
        if (node.type === 'file') {
            const isEntryName = entryPointNames.has(node.name) || node.name === 'cli.py';
            if (isEntryName) score += 3;
            
            const parts = node.filePath.split('/');
            if (parts.length <= 2) score += 1;

            if (fanOut[node.id] >= top10PercentFanOutThreshold && top10PercentFanOutThreshold > 0) score += 1;
            if (fanIn[node.id] <= bottom25PercentFanInThreshold) score += 1;

            if (score > 0) {
                entryPointCandidates.push({ id: node.id, score, name: node.name, summary: node.summary });
            }
        } else if (node.type === 'document') {
            if (node.name === 'README.md' && !node.filePath.includes('/')) {
                score += 5;
            } else if (node.name === 'README.md') {
                score += 3;
            } else if (node.name.endsWith('.md') && !node.filePath.includes('/')) {
                score += 2;
            }
            if (score > 0) {
                entryPointCandidates.push({ id: node.id, score, name: node.name, summary: node.summary });
            }
        }
    }
    entryPointCandidates.sort((a, b) => b.score - a.score);
    const topEntryPointCandidates = entryPointCandidates.slice(0, 5);

    const codeEntryCandidate = entryPointCandidates.filter(c => nodeMap[c.id].type === 'file')[0];
    let bfsTraversal = null;

    if (codeEntryCandidate) {
        const startNode = codeEntryCandidate.id;
        const order = [];
        const depthMap = {};
        const byDepth = {};

        const queue = [startNode];
        depthMap[startNode] = 0;

        while (queue.length > 0) {
            const current = queue.shift();
            order.push(current);
            const currentDepth = depthMap[current];

            if (!byDepth[currentDepth]) {
                byDepth[currentDepth] = [];
            }
            byDepth[currentDepth].push(current);

            const neighbors = adjacency[current] || [];
            for (const neighbor of neighbors) {
                if (depthMap[neighbor] === undefined) {
                    depthMap[neighbor] = currentDepth + 1;
                    queue.push(neighbor);
                }
            }
        }

        bfsTraversal = {
            startNode,
            order,
            depthMap,
            byDepth
        };
    }

    const nonCodeFiles = {
        documentation: [],
        infrastructure: [],
        data: [],
        config: []
    };

    for (const node of nodes) {
        if (node.type === 'document') {
            nonCodeFiles.documentation.push({ id: node.id, name: node.name, type: node.type, summary: node.summary });
        } else if (['service', 'pipeline', 'resource'].includes(node.type)) {
            nonCodeFiles.infrastructure.push({ id: node.id, name: node.name, type: node.type, summary: node.summary });
        } else if (['table', 'schema', 'endpoint'].includes(node.type)) {
            nonCodeFiles.data.push({ id: node.id, name: node.name, type: node.type, summary: node.summary });
        } else if (node.type === 'config') {
            nonCodeFiles.config.push({ id: node.id, name: node.name, type: node.type, summary: node.summary });
        }
    }

    const edgeMap = new Set();
    for (const edge of edges) {
        edgeMap.add(`${edge.source}->${edge.target}`);
    }

    const visitedPairs = new Set();
    const clusters = [];

    for (const edge of edges) {
        const { source, target } = edge;
        const pairKey = [source, target].sort().join(',');
        if (visitedPairs.has(pairKey)) continue;

        if (edgeMap.has(`${target}->${source}`)) {
            visitedPairs.add(pairKey);
            let cluster = [source, target];
            for (const node of nodes) {
                const nodeId = node.id;
                if (cluster.includes(nodeId)) continue;

                let connections = 0;
                for (const member of cluster) {
                    if (edgeMap.has(`${nodeId}->${member}`) || edgeMap.has(`${member}->${nodeId}`)) {
                        connections++;
                    }
                }
                if (connections >= 2) {
                    cluster.push(nodeId);
                }
            }

            let clusterEdgeCount = 0;
            for (let i = 0; i < cluster.length; i++) {
                for (let j = 0; j < cluster.length; j++) {
                    if (edgeMap.has(`${cluster[i]}->${cluster[j]}`)) {
                        clusterEdgeCount++;
                    }
                }
            }

            clusters.push({
                nodes: cluster,
                edgeCount: clusterEdgeCount
            });
        }
    }

    clusters.sort((a, b) => b.edgeCount - a.edgeCount);
    const topClusters = clusters.slice(0, 5);

    const layersOutput = {
        count: layers.length,
        list: layers.map(l => ({ id: l.id, name: l.name, description: l.description }))
    };

    const nodeSummaryIndex = {};
    for (const node of nodes) {
        nodeSummaryIndex[node.id] = {
            name: node.name,
            type: node.type,
            summary: node.summary
        };
    }

    const result = {
        scriptCompleted: true,
        entryPointCandidates: topEntryPointCandidates,
        fanInRanking,
        fanOutRanking,
        bfsTraversal,
        nonCodeFiles,
        clusters: topClusters,
        layers: layersOutput,
        nodeSummaryIndex,
        totalNodes: nodes.length,
        totalEdges: edges.length
    };

    try {
        fs.writeFileSync(outputPath, JSON.stringify(result, null, 2), 'utf8');
        console.log("Script completed successfully. Results written to", outputPath);
    } catch (e) {
        console.error("Failed to write results JSON:", e.message);
        process.exit(1);
    }
}

main();
