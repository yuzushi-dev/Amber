
import { useRef, useCallback } from 'react';
import { ForceGraphMethods } from 'react-force-graph-2d';

export const useGraphForce = () => {
    const graphRef = useRef<ForceGraphMethods | undefined>(undefined);

    const zoomToFit = useCallback(() => {
        if (graphRef.current) {
            graphRef.current.zoomToFit(400);
        }
    }, []);



    return {
        graphRef,
        zoomToFit,
    };
};
